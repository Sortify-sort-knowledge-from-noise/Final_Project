import os
import json
import requests
import random
import re
import base64
import time
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from dotenv import load_dotenv
from datetime import datetime, timedelta
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from .models import UserProfile, InterviewTemplate, InterviewTranscript, ProctorSnapshot, ProctorViolation
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.utils.decorators import method_decorator

# Optional import for Gemini; handle absence gracefully so the app still runs
try:
    import google.generativeai as genai
    from google.generativeai import GenerativeModel
except ImportError as e:
    genai = None
    GenerativeModel = None
    print(f"Warning: google.generativeai package not available: {e}")

# =====================================================
# CONFIGURATION
# =====================================================
# === Constants ===
load_dotenv()
INTERVIEW_DURATION = 60  # 30 minutes in seconds
PASS_SCORE_THRESHOLD = 5
MAX_FOLLOWUPS_PER_TOPIC = 2

# === AI Model Setup ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
eval_model = None

# Ollama (local) configuration - NEW
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3.2:1b")

if GEMINI_API_KEY and genai:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        eval_model = genai.GenerativeModel('gemini-2.5-flash-lite')
    except Exception as e:
        print(f"Warning: Failed to initialize google.generativeai: {e}")
        eval_model = None
else:
    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY not found. Evaluation will be skipped.")
    else:
        print("Warning: google.generativeai package not available. Evaluation will be skipped.")

# =====================================================
# UPDATED EVALUATION PROMPTS & SCORING SYSTEM
# =====================================================

PROMPT_EVALUATE_ANSWER = """
You are a strict technical interviewer evaluating candidate responses. Be critical but fair.

SCORING CRITERIA (1-10):
1-2: Completely wrong, off-topic, or no answer
3-4: Major misunderstandings, significant technical errors
5-6: Partial understanding with some technical inaccuracies
7-8: Mostly correct with minor errors or omissions
9-10: Excellent, comprehensive, technically accurate

TECHNICAL ASSESSMENT GUIDELINES:
- Deduct points for factual errors in core concepts
- Reward practical examples and real-world experience
- Penalize vague or non-technical responses
- Consider depth of explanation and clarity
- Look for specific technical details and terminology

RESPONSE FORMAT (JSON only):
{
  "evaluation_text": "Specific technical feedback highlighting strengths/weaknesses",
  "evaluation_score": <integer_1_to_10>,
  "technical_accuracy": <score_1-5>,
  "completeness": <score_1-5>,
  "clarity": <score_1-5>
}

Question: {question}
Answer: {answer}

Evaluate strictly based on technical merit.
"""

PROMPT_GENERATE_SUMMARY = """
You are a senior technical hiring manager. Generate a comprehensive interview evaluation report.

INTERVIEW DATA:
{conversation_history}

FINAL SCORE: {final_score}/10

REPORT REQUIREMENTS:
1. **Technical Competency Assessment** - Detailed analysis of technical skills demonstrated
2. **Strengths** - Specific technical capabilities shown
3. **Areas for Improvement** - Concrete technical gaps identified
4. **Recommendation** - Hire/No Hire decision with justification
5. **Overall Summary** - 2-3 paragraph comprehensive evaluation

SCORING INTERPRETATION:
- 9-10: Exceptional candidate, strong hire
- 7-8: Good candidate, consider for hire
- 5-6: Marginal candidate, needs significant improvement
- 1-4: Not suitable for technical role

Generate a professional, detailed evaluation report in Markdown format.
"""

# Transition phrases for dynamic interviews
TRANSITION_PHRASES = [
    "Great, that makes sense. Let's move on.",
    "Okay, I'm happy with that answer. For your next question:",
    "Good. Let's switch gears a bit.",
    "That's clear, thank you. Now, let's talk about a different topic.",
    "Excellent. Let's see how you do with this next question.",
    "Well said. Now, can you tell me..."
]

# Create evidence directories
os.makedirs('evidence', exist_ok=True)
os.makedirs('evidence/snapshots', exist_ok=True)
os.makedirs('evidence/logs', exist_ok=True)
os.makedirs('evidence/devices', exist_ok=True)

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def get_user_type(user):
    """Get user type from profile"""
    try:
        return user.userprofile.user_type
    except:
        return 'candidate'

def format_log_entry(role_name, text, evaluation=None):
    """Format transcript log entry"""
    if role_name == "user":
        entry = f"Candidate: {text}\n"
        if evaluation:
            entry += f"[Score: {evaluation.get('evaluation_score', 'N/A')}/10 - {evaluation.get('evaluation_text', 'N/A')}]\n"
        return entry + "\n"
    else:
        return f"Interviewer: {text}\n\n"

def normalize_speech_to_text(text):
    """
    Normalize speech-to-text output to fix common misrecognitions
    especially for technical terms
    """
    if not text:
        return text
    
    # Common STT misrecognitions for technical terms
    corrections = {
        r'\bsea\s+programming\b': 'C programming',
        r'\bsee\s+programming\b': 'C programming',
        r'\bc\s+programming\b': 'C programming',
        r'\bsea\s+plus\s+plus\b': 'C++',
        r'\bsee\s+plus\s+plus\b': 'C++',
        r'\bc\s+plus\s+plus\b': 'C++',
        r'\bjava\s+script\b': 'JavaScript',
        r'\bjava\s+scripts\b': 'JavaScript',
        r'\bpie\s+thon\b': 'Python',
        r'\bpie\s+ton\b': 'Python',
        r'\bsee\s+sharp\b': 'C#',
        r'\bc\s+sharp\b': 'C#',
        r'\barray\s+list\b': 'ArrayList',
        r'\blinked\s+list\b': 'Linked List',
        r'\bhash\s+map\b': 'HashMap',
        r'\bhash\s+table\b': 'HashTable',
        r'\bbinary\s+tree\b': 'Binary Tree',
        r'\bdata\s+base\b': 'database',
        r'\bstructured\s+query\s+language\b': 'SQL',
        r'\bsequel\b': 'SQL',
        r'\breact\s+dot\s+js\b': 'React.js',
        r'\bnode\s+dot\s+js\b': 'Node.js',
        r'\bvue\s+dot\s+js\b': 'Vue.js',
        r'\bangular\s+dot\s+js\b': 'Angular.js',
    }
    
    normalized_text = text
    for pattern, replacement in corrections.items():
        normalized_text = re.sub(pattern, replacement, normalized_text, flags=re.IGNORECASE)
    
    return normalized_text

# =====================================================
# ENHANCED EVALUATION FUNCTIONS
# =====================================================

def evaluate_answer_gemini(question, answer):
    """Strict evaluation with detailed technical assessment"""
    if not eval_model:
        return evaluate_answer_strict(question, answer)

    try:
        normalized_answer = normalize_speech_to_text(answer)
        
        eval_prompt = PROMPT_EVALUATE_ANSWER.format(
            question=question, 
            answer=normalized_answer
        )
        
        eval_response = eval_model.generate_content(eval_prompt)
        eval_json_str = eval_response.text.strip().lstrip("```json").rstrip("```")
        evaluation_data = json.loads(eval_json_str)

        # Validate and set default values
        evaluation_data.setdefault('evaluation_score', 5)
        evaluation_data.setdefault('technical_accuracy', 3)
        evaluation_data.setdefault('completeness', 3)
        evaluation_data.setdefault('clarity', 3)
        
        if not evaluation_data.get('evaluation_text'):
            evaluation_data['evaluation_text'] = generate_technical_feedback(
                evaluation_data['evaluation_score'], 
                normalized_answer
            )

        # Add normalization note if text was changed
        if normalized_answer != answer:
            evaluation_data['normalized_answer'] = normalized_answer

        # Log evaluation for debugging
        print(f"\n🔍 EVALUATION: Score {evaluation_data['evaluation_score']}/10")
        print(f"Question: {question}")
        print(f"Answer: {normalized_answer}")
        print(f"Feedback: {evaluation_data['evaluation_text']}")

        return evaluation_data

    except Exception as e:
        print(f"Gemini evaluation error: {e}")
        return evaluate_answer_strict(question, answer)

def evaluate_answer_strict(question, answer):
    """Strict rule-based evaluation with technical focus"""
    normalized_answer = normalize_speech_to_text(answer)
    answer_lower = normalized_answer.lower()
    
    # Technical term detection
    technical_terms = [
        'algorithm', 'data structure', 'memory', 'pointer', 'function', 'variable',
        'method', 'api', 'database', 'compile', 'debug', 'security', 'performance',
        'optimization', 'testing', 'debugging', 'struct', 'malloc', 'free', 'array',
        'string', 'loop', 'recursion', 'c programming', 'c++', 'python', 'java',
        'javascript', 'sql', 'framework', 'library', 'architecture', 'design pattern',
        'microservice', 'container', 'kubernetes', 'docker', 'cloud', 'api', 'rest',
        'graphql', 'database', 'sql', 'nosql', 'index', 'query', 'transaction'
    ]
    
    # Quality indicators
    quality_indicators = {
        'specific_example': ['for example', 'for instance', 'in my experience', 'i implemented'],
        'technical_detail': ['because', 'therefore', 'since', 'due to', 'the reason is'],
        'methodology': ['approach', 'methodology', 'process', 'workflow', 'pipeline'],
        'comparison': ['compared to', 'versus', 'better than', 'worse than', 'alternative'],
        'problem_solving': ['solve', 'fix', 'debug', 'troubleshoot', 'optimize']
    }
    
    # Calculate base score
    score = 5  # Start with neutral score
    
    # Technical content analysis
    technical_terms_found = [term for term in technical_terms if term in answer_lower]
    technical_score = min(3, len(technical_terms_found) * 0.5)
    score += technical_score
    
    # Quality indicators
    quality_score = 0
    for indicator, keywords in quality_indicators.items():
        if any(keyword in answer_lower for keyword in keywords):
            quality_score += 0.5
    score += min(2, quality_score)
    
    # Length and depth consideration
    word_count = len(normalized_answer.split())
    if word_count < 15:
        score -= 2  # Too brief
    elif word_count > 100:
        score += 1  # Detailed answer
    
    # Off-topic penalty
    off_topic_keywords = ['i dont know', 'not sure', 'no idea', 'cannot remember', 'irrelevant']
    if any(phrase in answer_lower for phrase in off_topic_keywords) and len(technical_terms_found) == 0:
        score = max(1, score - 3)
    
    # Ensure score is within bounds
    score = max(1, min(10, round(score)))
    
    # Generate appropriate feedback
    feedback = generate_technical_feedback(score, normalized_answer)
    
    result = {
        "evaluation_score": score,
        "evaluation_text": feedback,
        "technical_accuracy": max(1, min(5, round(score / 2))),
        "completeness": max(1, min(5, round(score / 2))),
        "clarity": max(1, min(5, round(score / 2))),
        "normalized_answer": normalized_answer
    }
    
    print(f"\n📊 STRICT EVALUATION: Score {score}/10")
    print(f"Technical terms found: {len(technical_terms_found)}")
    print(f"Feedback: {feedback}")
    
    return result

def generate_technical_feedback(score, answer):
    """Generate specific technical feedback based on score"""
    word_count = len(answer.split())
    
    if score >= 9:
        return "Excellent technical response demonstrating deep understanding and practical experience."
    elif score >= 7:
        return "Strong technical answer with good detail and accurate concepts."
    elif score >= 5:
        return "Adequate technical understanding but lacks depth or contains minor inaccuracies."
    elif score >= 3:
        return "Basic understanding shown but significant technical gaps or inaccuracies present."
    else:
        return "Insufficient technical response showing major misunderstandings or lack of knowledge."

def calculate_final_score(conversation_history):
    """Calculate weighted final score from all evaluations"""
    scores = []
    lines = conversation_history.split('\n')
    
    for line in lines:
        if 'Score:' in line:
            try:
                score_str = line.split('Score:')[1].split('/')[0].strip()
                score = int(score_str)
                scores.append(score)
            except (IndexError, ValueError):
                continue
    
    if not scores:
        return 0
    
    # Apply weighting - later answers matter more
    weighted_scores = []
    for i, score in enumerate(scores):
        weight = min(1.0, 0.7 + (i * 0.1))  # Later answers have slightly more weight
        weighted_scores.append(score * weight)
    
    final_score = sum(weighted_scores) / len(weighted_scores)
    return round(final_score, 2)

def generate_comprehensive_report(conversation_history, final_score):
    """Generate detailed interview report using Gemini"""
    if not eval_model:
        return generate_basic_report(conversation_history, final_score)
    
    try:
        prompt = PROMPT_GENERATE_SUMMARY.format(
            conversation_history=conversation_history,
            final_score=final_score
        )
        
        response = eval_model.generate_content(prompt)
        report = response.text.strip()
        
        # Ensure report is properly formatted
        if not report.startswith('#') and not report.startswith('##'):
            report = f"# Interview Evaluation Report\n\n## Final Score: {final_score}/10\n\n{report}"
        
        return report
        
    except Exception as e:
        print(f"Comprehensive report generation error: {e}")
        return generate_basic_report(conversation_history, final_score)

def generate_basic_report(conversation_history, final_score):
    """Generate basic report when Gemini is unavailable"""
    scores = []
    lines = conversation_history.split('\n')
    
    for line in lines:
        if 'Score:' in line:
            try:
                score_str = line.split('Score:')[1].split('/')[0].strip()
                score = int(score_str)
                scores.append(score)
            except (IndexError, ValueError):
                continue
    
    score_analysis = "No scores recorded"
    if scores:
        score_analysis = f"""
        - Number of questions: {len(scores)}
        - Average score: {final_score}/10
        - Highest score: {max(scores)}/10
        - Lowest score: {min(scores)}/10
        - Score distribution: {', '.join(map(str, scores))}
        """
    
    report = f"""
# Technical Interview Evaluation Report

## Overall Assessment
Final Score: **{final_score}/10**

{get_recommendation(final_score)}

## Performance Summary
{score_analysis}

## Evaluation Criteria
- **9-10**: Exceptional technical competency
- **7-8**: Strong technical skills with minor gaps  
- **5-6**: Basic competency needing development
- **1-4**: Significant technical improvements required

## Next Steps
Based on the interview performance, {get_next_steps(final_score)}

---
*Report generated automatically from interview transcript*
"""
    return report

def get_recommendation(score):
    """Get hiring recommendation based on score"""
    if score >= 8:
        return "✅ **Recommendation: Strong Hire** - Candidate demonstrates excellent technical capabilities."
    elif score >= 6:
        return "⚠️ **Recommendation: Consider with Training** - Candidate shows potential but needs development in some areas."
    else:
        return "❌ **Recommendation: Do Not Hire** - Candidate lacks required technical competency."

def get_next_steps(score):
    """Get appropriate next steps based on score"""
    if score >= 8:
        return "proceed to the next interview stage."
    elif score >= 6:
        return "consider for a junior role or provide specific technical training."
    else:
        return "the candidate should focus on improving fundamental technical skills before reapplying."

def generate_challenging_followup(question, answer):
    """Generate challenging follow-up for excellent answers"""
    challenges = [
        "That's an excellent answer. Now, considering edge cases, how would you handle...",
        "Great insight. Taking this further, how would you optimize this for scale?",
        "Well explained. What are the potential security implications of this approach?",
        "Good understanding. How would this solution work in a distributed system?"
    ]
    return random.choice(challenges)

def generate_related_question(question, answer):
    """Generate related question for good answers"""
    related = [
        "Good. Let's explore a related concept: ",
        "That makes sense. How does this compare to ",
        "Okay. What are the trade-offs of this approach versus "
    ]
    topics = ["microservices architecture", "database optimization", "caching strategies", "API design"]
    return random.choice(related) + random.choice(topics) + "?"

def generate_clarifying_question(question, answer):
    """Generate clarifying question for poor answers"""
    clarifications = [
        "Let me clarify: can you explain your understanding of ",
        "I want to make sure I understand your approach. Could you elaborate on ",
        "Let's go back to fundamentals. What is the core concept behind "
    ]
    core_concepts = ["that technology", "the underlying principle", "the main algorithm", "that architecture"]
    return random.choice(clarifications) + random.choice(core_concepts) + "?"

# =====================================================
# OLLAMA INTEGRATION
# =====================================================

def ollama_event_stream(convo, transcript_id):
    """
    Stream responses from local Ollama instance.
    Expects convo to be list of dicts with 'role' and 'content'.
    """
    messages = [{"role": c["role"], "content": c["content"]} for c in convo]
    payload = {"model": MODEL_NAME, "messages": messages, "stream": True}
    reply = ""
    try:
        with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=60) as r:
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line.decode("utf-8"))
                    token = obj.get("message", {}).get("content", "")
                except Exception:
                    token = ""
                if token:
                    reply += token
                    yield f"data: {json.dumps({'text': token})}\n\n"
        # send done chunk
        yield f"data: {json.dumps({'done_text': reply})}\n\n"
        yield "data: [DONE]\n\n"
        # Save final reply to transcript and session conversation
        try:
            if transcript_id and transcript_id != "session_only":
                tr = InterviewTranscript.objects.get(id=transcript_id)
                tr.conversation_history += format_log_entry("assistant", reply)
                tr.save()
            convo.append({"role": "assistant", "content": reply})
        except Exception as e:
            print("Error saving ollama reply to transcript:", e)
    except Exception as e:
        print("Ollama stream error:", e)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

# =====================================================
# TEMPLATE-BASED QUESTION GENERATION
# =====================================================

def generate_system_prompt_from_template(template):
    """Generate intelligent system prompt from template"""
    topics_text = ", ".join(template.topics) if template.topics else "core concepts"
    
    prompt = f"""
You are a senior technical interviewer conducting a {template.duration}-minute technical screening for a {template.role} position.

TECHNICAL TOPICS TO ASSESS: {topics_text}
DIFFICULTY LEVEL: {template.difficulty}

CRITICAL INSTRUCTIONS:
1. Generate INTELLIGENT, VARIED technical questions that comprehensively assess the candidate's knowledge of: {topics_text}
2. Ask only ONE question at a time
3. For each topic, you can ask up to {MAX_FOLLOWUPS_PER_TOPIC} follow-up questions to probe deeper
4. Questions should be appropriate for {template.difficulty} level
5. Make questions practical, scenario-based, and relevant to real-world {template.role} work
6. Do NOT provide answers, hints, or evaluations
7. Stay strictly on technical topics - do not entertain off-topic discussions
8. After assessing all topics, conclude the interview naturally without repeating questions
9. Vary your question types: conceptual, practical implementation, problem-solving, debugging, optimization

QUESTION TYPES TO USE:
- Conceptual: "Explain how X works and when you would use it"
- Practical: "How would you implement X in a real project?"
- Problem-solving: "Given scenario Y, how would you approach it using X?"
- Debugging: "What would you do if X is not working as expected?"
- Comparison: "How does X compare to Y in terms of performance/usability?"
- Best practices: "What are the key best practices when working with X?"

Your goal is to thoroughly assess the candidate's technical competence in {topics_text}.
"""
    return prompt

def generate_intelligent_question(topic, difficulty, followup_count=0, previous_answer=None, conversation_context=None):
    """Generate intelligent, context-aware questions based on previous answers"""
    
    # If we have a previous answer and conversation context, use Gemini for intelligent follow-ups
    if followup_count > 0 and previous_answer and eval_model:
        try:
            followup_prompt = f"""
            Based on the candidate's previous answer about {topic}, generate an intelligent follow-up question that:
            1. Probes deeper into areas that need clarification
            2. Challenges their understanding if the answer was superficial
            3. Asks for practical examples or implementation details
            4. Connects to related concepts
            
            Previous question: {conversation_context.get('last_question', 'No context')}
            Candidate's answer: {previous_answer}
            Current topic: {topic}
            Difficulty level: {difficulty}
            Follow-up count: {followup_count}
            
            Generate only the question, no additional text.
            """
            
            response = eval_model.generate_content(followup_prompt)
            question = response.text.strip()
            
            if question and len(question) > 10:  # Basic validation
                return question
        except Exception as e:
            print(f"Intelligent follow-up generation failed: {e}")
            # Fall through to rule-based generation
    
    # Rule-based question generation as fallback
    question_pools = {
        'beginner': {
            'conceptual': [
                f"Can you explain what {topic} is in simple terms?",
                f"What are the basic concepts someone needs to know about {topic}?",
                f"How would you describe {topic} to someone new to programming?",
                f"What problem does {topic} help solve?"
            ],
            'practical': [
                f"Can you show a simple example of how to use {topic}?",
                f"What's the most basic way to implement {topic}?",
                f"Walk me through a beginner-level example of {topic}."
            ]
        },
        'intermediate': {
            'conceptual': [
                f"Explain the core architecture and components of {topic}.",
                f"What are the key design patterns used in {topic}?",
                f"How does {topic} handle common challenges like performance or security?",
                f"What are the trade-offs when using {topic} versus alternatives?"
            ],
            'practical': [
                f"Show me how you would implement {topic} in a real-world scenario.",
                f"How would you optimize {topic} for better performance?",
                f"Walk me through debugging a common issue with {topic}.",
                f"How would you integrate {topic} with other systems?"
            ],
            'problem_solving': [
                f"Given a scenario where [related problem], how would you use {topic} to solve it?",
                f"What approach would you take to scale {topic} for high traffic?",
                f"How would you troubleshoot performance issues in {topic}?"
            ]
        },
        'advanced': {
            'conceptual': [
                f"Explain the internal mechanics and advanced features of {topic}.",
                f"What are the limitations of {topic} and how do you work around them?",
                f"How would you design a distributed system using {topic}?",
                f"What are the security considerations at scale for {topic}?"
            ],
            'practical': [
                f"Design and implement a complex system using {topic}.",
                f"How would you optimize {topic} for maximum performance under load?",
                f"Show me how you would implement advanced features of {topic}.",
                f"How would you handle fault tolerance and recovery in {topic}?"
            ],
            'architectural': [
                f"How would you architect a large-scale system using {topic}?",
                f"What design patterns and principles are most important for {topic} at scale?",
                f"How does {topic} fit into microservices architecture?",
                f"What are the deployment and operational considerations for {topic}?"
            ]
        }
    }
    
    # Select question type based on follow-up count
    pool = question_pools.get(difficulty, question_pools['intermediate'])
    
    if followup_count == 0:
        # First question - mix conceptual and practical
        question_types = ['conceptual', 'practical']
    elif followup_count == 1:
        # Second question - more practical/problem-solving
        question_types = ['practical', 'problem_solving']
    else:
        # Third+ question - advanced/challenging
        question_types = ['problem_solving', 'architectural'] if difficulty == 'advanced' else ['practical', 'problem_solving']
    
    # Filter available question types
    available_types = [qt for qt in question_types if qt in pool]
    if not available_types:
        available_types = list(pool.keys())
    
    selected_type = random.choice(available_types)
    
    if pool[selected_type]:
        return random.choice(pool[selected_type])
    else:
        return f"Tell me about your experience with {topic} and any challenging problems you've solved with it."

# =====================================================
# AUTHENTICATION VIEWS
# =====================================================

def index_view(request):
    """Landing page - redirects based on authentication"""
    if request.user.is_authenticated:
        user_type = get_user_type(request.user)
        if user_type == 'recruiter':
            return redirect('recruiter_dashboard')
        return redirect('chat_page')
    return redirect('login_view')

@csrf_protect
def login_view(request):
    """Login page with proper CSRF handling"""
    if request.user.is_authenticated:
        user_type = get_user_type(request.user)
        if user_type == 'recruiter':
            return redirect('recruiter_dashboard')
        return redirect('chat_page')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Remove the session flush as it can cause CSRF issues
            login(request, user)

            user_type = get_user_type(user)
            if user_type == 'recruiter':
                return redirect('recruiter_dashboard')
            return redirect('chat_page')
        else:
            return render(request, 'chatapp/login.html', {'error': 'Invalid credentials'})

    return render(request, 'chatapp/login.html')

@csrf_protect
def register_view(request):
    """Registration page with proper CSRF handling"""
    if request.user.is_authenticated:
        user_type = get_user_type(request.user)
        if user_type == 'recruiter':
            return redirect('recruiter_dashboard')
        return redirect('chat_page')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        user_type = request.POST.get('user_type', 'candidate')
        company = request.POST.get('company', '')

        errors = []

        if not username:
            errors.append('Username is required')
        elif len(username) < 3:
            errors.append('Username must be at least 3 characters')

        if not email:
            errors.append('Email is required')
        elif '@' not in email:
            errors.append('Enter a valid email address')

        if not password:
            errors.append('Password is required')
        elif len(password) < 6:
            errors.append('Password must be at least 6 characters')

        if password != confirm_password:
            errors.append('Passwords do not match')

        if User.objects.filter(username=username).exists():
            errors.append('Username already exists')

        if User.objects.filter(email=email).exists():
            errors.append('Email already exists')

        if errors:
            return render(request, 'chatapp/register.html', {'error': ' | '.join(errors)})

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            UserProfile.objects.create(
                user=user,
                user_type=user_type,
                company=company if user_type == 'recruiter' else None
            )

            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                if user_type == 'recruiter':
                    return redirect('recruiter_dashboard')
                return redirect('chat_page')
            else:
                return redirect('login_view')

        except Exception as e:
            return render(request, 'chatapp/register.html', {'error': f'Registration error: {str(e)}'})

    return render(request, 'chatapp/register.html')
      
def logout_view(request):
    """Logout and clear session"""
    logout(request)
    request.session.flush()
    return redirect('login_view')

# =====================================================
# PROFILE VIEWS
# =====================================================

@login_required
def profile_view(request):
    """User profile page with proper history"""
    try:
        profile = UserProfile.objects.get(user=request.user)
        user_type = profile.user_type

        if request.method == 'POST' and request.FILES.get('photo'):
            profile.photo = request.FILES['photo']
            profile.save()
            return redirect('profile_view')

        if user_type == 'recruiter':
            templates = InterviewTemplate.objects.filter(
                created_by=request.user).order_by('-created_at')
            
            # Get all interviews conducted using this recruiter's templates
            template_interviews = {}
            for template in templates:
                interviews = InterviewTranscript.objects.filter(
                    template=template,
                    completed=True  # Only show completed interviews
                ).select_related('user', 'user__userprofile').order_by('-created_at')
                
                # Add calculated data for display
                for interview in interviews:
                    interview.violation_count = ProctorViolation.objects.filter(
                        interview=interview).count()
                    interview.suspended = interview.violation_count > 0
                
                template_interviews[template.id] = {
                    'template': template,
                    'interviews': interviews,
                    'total_candidates': len(interviews),
                    'avg_score': sum(i.final_score for i in interviews if i.final_score) / len(interviews) if interviews else 0,
                    'suspended_count': sum(1 for i in interviews if i.suspended)
                }

            context = {
                'profile': profile,
                'templates': templates,
                'template_interviews': template_interviews,
            }
        else:
            # Candidate view - show their completed interviews
            interviews = InterviewTranscript.objects.filter(
                user=request.user, 
                completed=True
            ).order_by('-created_at')
            
            interview_count = interviews.count()

            # Add violation counts for display
            for interview in interviews:
                interview.violation_count = ProctorViolation.objects.filter(
                    interview=interview).count()
                interview.snapshot_count = ProctorSnapshot.objects.filter(
                    interview=interview).count()

            context = {
                'profile': profile,
                'interviews': interviews,
                'interview_count': interview_count,
            }

        return render(request, 'chatapp/profile.html', context)

    except Exception as e:
        print(f"Profile view error: {e}")
        return render(request, 'chatapp/profile.html', {
            'profile': None,
            'error': 'Error loading profile'
        })

# =====================================================
# CANDIDATE VIEWS
# =====================================================

@login_required
def chat_page(request):
    """Candidate interview page"""
    user_type = get_user_type(request.user)

    if user_type == 'recruiter':
        return redirect('recruiter_dashboard')

    return render(request, "chatapp/chat.html")

# =====================================================
# RECRUITER VIEWS
# =====================================================

@login_required
def recruiter_dashboard(request):
    """Recruiter dashboard with proper candidate analytics"""
    user_type = get_user_type(request.user)
    if user_type != 'recruiter':
        return redirect('chat_page')

    templates = InterviewTemplate.objects.filter(created_by=request.user)
    
    # Get analytics for each template
    template_analytics = []
    for template in templates:
        interviews = InterviewTranscript.objects.filter(
            template=template, 
            completed=True
        )
        total_candidates = interviews.count()
        completed_interviews = interviews.count()  # All are completed now
        
        # Calculate average scores from final_score field
        total_score = 0
        score_count = 0
        suspended_count = 0
        
        for interview in interviews:
            if interview.final_score:
                total_score += interview.final_score
                score_count += 1
            
            if ProctorViolation.objects.filter(interview=interview).exists():
                suspended_count += 1
        
        avg_score = total_score / score_count if score_count > 0 else 0
        
        template_analytics.append({
            'template': template,
            'total_candidates': total_candidates,
            'completed_interviews': completed_interviews,
            'avg_score': round(avg_score, 1),
            'suspended_count': suspended_count,
            'completion_rate': 100 if total_candidates > 0 else 0
        })

    return render(request, 'chatapp/recruiter_dashboard.html', {
        'templates': templates,
        'template_analytics': template_analytics
    })

# =====================================================
# TEMPLATE API ENDPOINTS
# =====================================================

@login_required
def get_templates(request):
    """Get recruiter's templates"""
    user_type = get_user_type(request.user)
    if user_type != 'recruiter':
        return JsonResponse({'error': 'Access denied'}, status=403)

    templates = InterviewTemplate.objects.filter(created_by=request.user)
    template_list = []

    for template in templates:
        template_list.append({
            'id': template.id,
            'title': template.title,
            'role': template.role,
            'difficulty': template.difficulty,
            'topics': template.topics,
            'duration': template.duration,
            'created_at': template.created_at.isoformat()
        })

    return JsonResponse({'templates': template_list})

@login_required
def get_available_templates(request):
    """Get all active templates for candidates"""
    templates = InterviewTemplate.objects.filter(is_active=True)
    template_list = []

    for template in templates:
        template_list.append({
            'id': template.id,
            'title': template.title,
            'role': template.role,
            'difficulty': template.difficulty,
            'duration': template.duration,
            'topics': template.topics
        })

    return JsonResponse({'templates': template_list})

@login_required
def create_template(request):
    """Create new template with proper error handling"""
    user_type = get_user_type(request.user)
    if user_type != 'recruiter':
        return JsonResponse({'error': 'Access denied'}, status=403)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            template = InterviewTemplate.objects.create(
                created_by=request.user,
                title=data.get('title', 'Untitled Template'),
                role=data.get('role', 'General Role'),
                difficulty=data.get('difficulty', 'intermediate'),
                topics=data.get('topics', []),
                duration=data.get('duration', 30),
                is_active=True
            )
            return JsonResponse({
                'id': template.id,
                'title': template.title,
                'message': 'Template created successfully'
            })
        except Exception as e:
            print(f"Template creation error: {e}")
            return JsonResponse({'error': f'Database error: {str(e)}'}, status=400)

    return JsonResponse({'error': 'Invalid method'}, status=405)

@login_required
def get_template_detail(request, template_id):
    """Get single template details"""
    user_type = get_user_type(request.user)
    if user_type != 'recruiter':
        return JsonResponse({'error': 'Access denied'}, status=403)

    try:
        template = InterviewTemplate.objects.get(
            id=template_id, created_by=request.user)
        return JsonResponse({
            'id': template.id,
            'title': template.title,
            'role': template.role,
            'difficulty': template.difficulty,
            'topics': template.topics,
            'duration': template.duration
        })
    except InterviewTemplate.DoesNotExist:
        return JsonResponse({'error': 'Template not found'}, status=404)

@login_required
def update_template(request, template_id):
    """Update template"""
    user_type = get_user_type(request.user)
    if user_type != 'recruiter':
        return JsonResponse({'error': 'Access denied'}, status=403)

    if request.method == 'POST':
        try:
            template = InterviewTemplate.objects.get(
                id=template_id, created_by=request.user)
            data = json.loads(request.body)

            template.title = data.get('title', template.title)
            template.role = data.get('role', template.role)
            template.difficulty = data.get('difficulty', template.difficulty)
            template.topics = data.get('topics', template.topics)
            template.duration = data.get('duration', template.duration)
            template.save()

            return JsonResponse({'message': 'Template updated successfully'})
        except InterviewTemplate.DoesNotExist:
            return JsonResponse({'error': 'Template not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Invalid method'}, status=405)

@login_required
def delete_template(request, template_id):
    """Delete template"""
    user_type = get_user_type(request.user)
    if user_type != 'recruiter':
        return JsonResponse({'error': 'Access denied'}, status=403)

    try:
        template = InterviewTemplate.objects.get(
            id=template_id, created_by=request.user)
        template.delete()
        return JsonResponse({'message': 'Template deleted successfully'})
    except InterviewTemplate.DoesNotExist:
        return JsonResponse({'error': 'Template not found'}, status=404)

# =====================================================
# INTERVIEW ENGINE WITH TEMPLATE SUPPORT & OLLAMA DYNAMIC MODE
# =====================================================

def clear_interview_session(request):
    """Clear all interview-related session data"""
    interview_keys = [
        "conversation", "role", "asked_questions", "current_question_index",
        "interview_mode", "follow_up_count", "poor_answer_count", "off_topic_count",
        "interview_started", "transcript_id", "interview_start_time", "timer_set",
        "interview_suspended", "suspension_reason", "template_id", "transcript_log",
        "asked_topics", "current_topic", "current_topic_followups", "topic_questions",
        "current_topic_index", "interview_completed"
    ]
    for key in interview_keys:
        if key in request.session:
            del request.session[key]

def check_interview_time_remaining(request):
    """Check remaining time"""
    if not request.session.get("interview_start_time"):
        return INTERVIEW_DURATION
    elapsed = time.time() - request.session["interview_start_time"]
    remaining = INTERVIEW_DURATION - elapsed
    return max(0, remaining)

def is_interview_suspended(request):
    """Check if interview is suspended"""
    return request.session.get("interview_suspended", False)

def is_interview_completed(request):
    """Check if interview is completed"""
    return request.session.get("interview_completed", False)

def suspend_interview_session(request, reason):
    """Suspend interview"""
    request.session["interview_suspended"] = True
    request.session["suspension_reason"] = reason
    request.session.modified = True

def complete_interview_session(request):
    """Mark interview as completed"""
    request.session["interview_completed"] = True
    request.session.modified = True

def get_conversation(request):
    return request.session.get("conversation", [])

def save_conversation(request, convo):
    request.session["conversation"] = convo
    request.session.modified = True

@csrf_exempt
@login_required
def start_interview(request):
    """Start interview endpoint with template support and dynamic mode"""
    clear_interview_session(request)

    try:
        data = json.loads(request.body.decode("utf-8"))
        role_name = data.get("role", "C Developer").strip()
        template_id = data.get("template_id")
        use_dynamic_mode = data.get("dynamic_mode", False)  # NEW: Dynamic mode flag

        template = None
        system_prompt = ""
        first_q = ""

        if template_id and not use_dynamic_mode:
            try:
                template = InterviewTemplate.objects.get(id=template_id)
                system_prompt = generate_system_prompt_from_template(template)

                # Generate first question based on first topic
                # Always start with a fixed introductory question for template-based interviews
                # so we can learn candidate strengths before diving into topic-specific questions.
                first_q = "What are your strengths and name one topic where you are strongest?"

                # Initialize topic tracking so follow-ups use the template topics
                if template.topics:
                    first_topic = template.topics[0]
                    
                    # Initialize topic tracking
                    request.session["current_topic_index"] = 0
                    request.session["current_topic_followups"] = 0
                    request.session["interview_completed"] = False
                else:
                    first_q = f"Let's begin the {template.role} interview. Can you tell me about your experience with this role?"

                request.session["template_id"] = template_id
                interview_mode = "template"
            except InterviewTemplate.DoesNotExist:
                return JsonResponse({'error': 'Template not found'}, status=404)
        else:
            # NEW: Dynamic mode using Ollama
            if use_dynamic_mode:
                system_prompt = (
                    f"You are an AI technical interviewer. Your persona is professional, encouraging, and focused. "
                    f"You are conducting an adaptive interview for a {role_name} position. "
                    f"Your SOLE objective is to ask one concise, relevant follow-up question that directly builds on the candidate's most recent answer. "
                    f"Do not introduce new topics, give answers, provide evaluations, or summarize their response.\n\n"
                    f"Core rules:\n"
                    f"If you are unclear with what the user has said, then dont try and predict what they are trying to say, instead ask them again"
                    f"1. Analyze answer: Read the user's last reply and identify the most relevant claim, example, decision, or gap.\n"
                    f"2. Ask exactly ONE follow-up question that continues the same point:\n"
                    f"   - If the answer shows clear understanding or depth: ask a deeper, more complex or edge-case question about that same element.\n"
                    f"   - If the answer is vague, incomplete, or unclear: ask a simpler clarifying or guiding question to prompt elaboration.\n"
                    f"3. Stay on topic: Never change the subject. Every question must be a direct follow-up to content in the user's last message.\n"
                    f"4. Handle off-topic replies: If the user's response is unrelated, politely redirect with a single follow-up.\n"
                    f"5. Be brief and neutral: Keep the question conversational, 1–2 sentences, encouraging in tone.\n"
                    f"6. No answers or hints: Do not provide solutions — only a question to elicit more detail.\n"
                    f"7. Reference their text when helpful: You may include a short quoted fragment to ground the question.\n"
                    f"8. Adjust difficulty implicitly: Probe deeper for signs of competence; ask for clarification when uncertain.\n"
                    f"9. Professionalism and safety: Use neutral, inclusive language.\n"
                    f"10. Output constraints: Return only the single follow-up question text (no preface, no explanation).\n"
                )
                first_q = f"Let's begin the {role_name} interview. Can you tell me about your relevant experience and what interests you about this position?"
                interview_mode = "dynamic"
            else:
                # Fallback to default
                system_prompt = """You are a technical interviewer. Ask clear, focused technical questions one at a time about programming, data structures, algorithms, and software engineering principles."""
                first_q = f"Let's begin the {role_name} interview. What interests you about this position?"
                interview_mode = "default"

        convo = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": first_q}
        ]

        session_data = {
            "conversation": convo,
            "role": role_name,
            "interview_mode": interview_mode,
            "follow_up_count": 0,
            "poor_answer_count": 0,
            "off_topic_count": 0,
            "interview_started": True,
            "interview_start_time": time.time(),
            "timer_set": True,
            "interview_suspended": False,
            "interview_completed": False
        }

        if template_id and not use_dynamic_mode:
            session_data["template_id"] = template_id

        request.session.update(session_data)

        # Create transcript
        start_time = datetime.now()
        template_info = f" (Template: {template.title})" if template else ""
        mode_info = " (Dynamic Mode)" if use_dynamic_mode else ""
        header = f"Interview for {role_name}{template_info}{mode_info} at {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        try:
            transcript = InterviewTranscript.objects.create(
                user=request.user,
                template=template,
                role=role_name,
                conversation_history=header +
                format_log_entry("assistant", first_q),
                completed=False
            )
            request.session["transcript_id"] = transcript.id
            print(f"✅ Transcript created with ID: {transcript.id}")
        except Exception as e:
            print(f"❌ Transcript creation error: {e}")
            # Fallback: create a basic transcript record anyway
            try:
                transcript = InterviewTranscript.objects.create(
                    user=request.user,
                    template=None,
                    role=role_name,
                    conversation_history=header + "Error creating full transcript\n",
                    completed=False
                )
                request.session["transcript_id"] = transcript.id
            except Exception as e2:
                print(f"❌ Fallback transcript also failed: {e2}")
                request.session["transcript_id"] = "session_only"
                request.session["transcript_log"] = header + \
                    format_log_entry("assistant", first_q)

        return JsonResponse({"reply": first_q})

    except Exception as e:
        print(f"❌ Start interview error: {e}")
        return JsonResponse({'error': f'Failed to start interview: {str(e)}'}, status=500)

# =====================================================
# ENHANCED STREAM CHAT WITH BETTER EVALUATION
# =====================================================

@csrf_exempt
@login_required
def stream_chat(request):
    """Stream chat with enhanced evaluation system"""
    if is_interview_suspended(request):
        reason = request.session.get("suspension_reason", "Violation detected")
        return JsonResponse({
            "error": f"INTERVIEW SUSPENDED: {reason}",
            "suspended": True
        }, status=400)

    if is_interview_completed(request):
        return JsonResponse({
            "error": "Interview completed",
            "completed": True
        }, status=400)

    time_remaining = check_interview_time_remaining(request)
    if time_remaining <= 0:
        # Auto-end interview when time expires
        try:
            transcript_id = request.session.get("transcript_id")
            if transcript_id and transcript_id != "session_only":
                tr = InterviewTranscript.objects.get(id=transcript_id)
                tr.completed = True
                final_score = calculate_final_score(tr.conversation_history)
                tr.final_score = final_score
                tr.final_report = generate_comprehensive_report(tr.conversation_history, final_score)
                tr.conversation_history += f"\n\n[INTERVIEW ENDED] Time completed at {datetime.now().strftime('%H:%M:%S')}"
                tr.save()
        except Exception as e:
            print(f"Time end transcript update error: {e}")

        complete_interview_session(request)
        return JsonResponse({"error": "Interview time expired", "time_up": True}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
        user_input = data.get("message", "").strip()

        if not user_input:
            return JsonResponse({"error": "Empty message"}, status=400)

        if not request.session.get("interview_started"):
            return JsonResponse({"error": "Interview not started"}, status=400)

        convo = get_conversation(request)
        transcript_id = request.session.get("transcript_id")

        if not convo:
            return JsonResponse({"error": "Interview not initialized"}, status=400)

        # Enhanced evaluation with strict scoring
        last_question = convo[-1].get("content", "") if convo else "No previous question"
        evaluation = evaluate_answer_gemini(last_question, user_input)

        # Add to conversation with evaluation data
        normalized_answer = evaluation.get('normalized_answer', user_input)
        convo.append({
            "role": "user", 
            "content": normalized_answer,
            "evaluation": evaluation,
            "timestamp": datetime.now().isoformat()
        })
        save_conversation(request, convo)

        # Enhanced transcript logging
        try:
            if transcript_id and transcript_id != "session_only":
                tr = InterviewTranscript.objects.get(id=transcript_id)
                log_entry = format_log_entry("user", normalized_answer, evaluation)
                tr.conversation_history += log_entry
                
                # Add detailed evaluation metrics
                tr.conversation_history += f"[Technical Accuracy: {evaluation.get('technical_accuracy', 'N/A')}/5 | "
                tr.conversation_history += f"Completeness: {evaluation.get('completeness', 'N/A')}/5 | "
                tr.conversation_history += f"Clarity: {evaluation.get('clarity', 'N/A')}/5]\n"
                
                tr.save()
            elif transcript_id == "session_only":
                request.session["transcript_log"] = request.session.get(
                    "transcript_log", "") + format_log_entry("user", normalized_answer, evaluation)
        except Exception as e:
            print(f"❌ Enhanced transcript logging error: {e}")

        # Check interview mode and handle accordingly
        interview_mode = request.session.get("interview_mode", "default")
        
        # Dynamic mode using Ollama
        if interview_mode == "dynamic":
            try:
                # For dynamic flow we push a lightweight system instruction before streaming
                dynamic_system = (
                    "You are a concise technical interviewer. Read the conversation and produce exactly one follow-up question "
                    "that directly continues the candidate's last answer. Keep it short (1-2 sentences). Do not provide answers or evaluations."
                )
                # Prepend system message for this call only
                convo_for_ollama = [{"role": "system", "content": dynamic_system}] + convo
                return StreamingHttpResponse(ollama_event_stream(convo_for_ollama, transcript_id), content_type="text/event-stream")
            except Exception as e:
                print("Error calling Ollama:", e)
                # Fallback to default prompt if Ollama fails
                fallback_next = "Sorry, the dynamic generator is currently unavailable. Please continue: can you give an example to illustrate your approach?"
                convo.append({"role": "assistant", "content": fallback_next})
                save_conversation(request, convo)
                try:
                    if transcript_id and transcript_id != "session_only":
                        tr = InterviewTranscript.objects.get(id=transcript_id)
                        tr.conversation_history += format_log_entry("assistant", fallback_next)
                        tr.save()
                except Exception as e:
                    print("Fallback logging error:", e)
                def _fb():
                    yield f"data: {json.dumps({'text': fallback_next, 'done_text': fallback_next})}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingHttpResponse(_fb(), content_type="text/event-stream")

        # Template-based interview mode (existing functionality)
        template_id = request.session.get("template_id")
        
        if template_id:
            try:
                template = InterviewTemplate.objects.get(id=template_id)
                current_topic_index = request.session.get("current_topic_index", 0)
                current_followups = request.session.get("current_topic_followups", 0)
                
                # Check if we have more topics to cover
                if current_topic_index < len(template.topics):
                    current_topic = template.topics[current_topic_index]
                    
                    # Prepare conversation context for intelligent question generation
                    conversation_context = {
                        'last_question': last_question,
                        'user_answer': normalized_answer,
                        'evaluation_score': evaluation.get('evaluation_score', 0)
                    }
                    
                    # Check if we should ask follow-up or move to next topic
                    if current_followups < MAX_FOLLOWUPS_PER_TOPIC:
                        # Ask intelligent follow-up question
                        next_q = generate_intelligent_question(
                            current_topic, 
                            template.difficulty, 
                            current_followups + 1,
                            normalized_answer,
                            conversation_context
                        )
                        request.session["current_topic_followups"] = current_followups + 1
                    else:
                        # Move to next topic
                        current_topic_index += 1
                        request.session["current_topic_index"] = current_topic_index
                        request.session["current_topic_followups"] = 0
                        
                        if current_topic_index < len(template.topics):
                            next_topic = template.topics[current_topic_index]
                            next_q = generate_intelligent_question(next_topic, template.difficulty)
                        else:
                            # All topics covered - end interview
                            next_q = "Thank you for completing the technical assessment. This concludes our interview. Your responses have been recorded and will be reviewed by our team."
                            complete_interview_session(request)
                            
                            # Update transcript with completion status and final score
                            try:
                                if transcript_id and transcript_id != "session_only":
                                    tr = InterviewTranscript.objects.get(id=transcript_id)
                                    tr.completed = True
                                    final_score = calculate_final_score(tr.conversation_history)
                                    tr.final_score = final_score
                                    tr.final_report = generate_comprehensive_report(tr.conversation_history, final_score)
                                    tr.save()
                            except Exception as e:
                                print(f"Complete transcript error: {e}")
                else:
                    # Interview completed
                    next_q = "Thank you for completing the interview. Your responses have been recorded."
                    complete_interview_session(request)
                    
                    # Update transcript
                    try:
                        if transcript_id and transcript_id != "session_only":
                            tr = InterviewTranscript.objects.get(id=transcript_id)
                            tr.completed = True
                            final_score = calculate_final_score(tr.conversation_history)
                            tr.final_score = final_score
                            tr.final_report = generate_comprehensive_report(tr.conversation_history, final_score)
                            tr.save()
                    except Exception as e:
                        print(f"Complete transcript error: {e}")
            except InterviewTemplate.DoesNotExist:
                next_q = "I apologize, but there seems to be an issue with the interview template. Please contact support."
        else:
            # Default mode - adaptive question flow based on answer quality
            score = evaluation.get("evaluation_score", 5)
            
            if score >= 8:
                next_q = generate_challenging_followup(last_question, normalized_answer)
            elif score >= 6:
                next_q = generate_related_question(last_question, normalized_answer)
            elif score >= 4:
                next_q = generate_clarifying_question(last_question, normalized_answer)
            else:
                next_q = "Let me ask a more fundamental question to build upon: " + generate_intelligent_question("programming fundamentals", "beginner")

        # Add next question to conversation
        convo.append({"role": "assistant", "content": next_q})
        save_conversation(request, convo)

        # Log to transcript
        try:
            if transcript_id and transcript_id != "session_only":
                tr = InterviewTranscript.objects.get(id=transcript_id)
                tr.conversation_history += format_log_entry("assistant", next_q)
                tr.save()
            elif transcript_id == "session_only":
                request.session["transcript_log"] = request.session.get(
                    "transcript_log", "") + format_log_entry("assistant", next_q)
        except Exception as e:
            print(f"❌ AI response transcript error: {e}")

        def generate():
            yield f"data: {json.dumps({'text': next_q, 'done_text': next_q})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingHttpResponse(generate(), content_type="text/event-stream")

    except Exception as e:
        print(f"❌ Stream chat error: {e}")
        return JsonResponse({'error': f'Internal server error: {str(e)}'}, status=500)

@csrf_exempt
@login_required
def check_time(request):
    """Check remaining time"""
    time_remaining = check_interview_time_remaining(request)
    suspended = is_interview_suspended(request)
    completed = is_interview_completed(request)
    return JsonResponse({
        "time_remaining": time_remaining,
        "total_time": INTERVIEW_DURATION,
        "suspended": suspended,
        "completed": completed
    })

# =====================================================
# PROCTORING ENDPOINTS
# =====================================================

@csrf_exempt
@login_required
def log_event(request):
    """Log proctoring event"""
    try:
        payload = json.loads(request.body.decode("utf-8")) or {}
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")

        # Categorize logs based on event type
        event_type = payload.get('type', 'unknown')
        kind = payload.get('kind', 'unknown')

        if event_type == 'warning' and kind == 'device':
            # Device detection events get special handling
            fname = f'evidence/devices/device_detection_{ts}.json'
        elif event_type == 'suspend':
            # Suspension events are critical
            fname = f'evidence/logs/suspend_{ts}.json'
        elif event_type == 'warning':
            # Regular warnings
            fname = f'evidence/logs/warning_{kind}_{ts}.json'
        else:
            # Other events
            fname = f'evidence/logs/event_{event_type}_{ts}.json'

        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f'Event logged: {event_type} ({kind}) -> {fname}')

        # Print critical events to console immediately
        if event_type == 'suspend' or (event_type == 'warning' and kind == 'device'):
            print(
                f'🚨 CRITICAL: {event_type.upper()} - {payload.get("reason", "No reason provided")}')

        # Also log to database if we have a transcript
        try:
            transcript_id = request.session.get("transcript_id")
            if transcript_id and transcript_id != "session_only":
                tr = InterviewTranscript.objects.get(id=transcript_id)
                ProctorViolation.objects.create(
                    interview=tr,
                    violation_type=event_type,
                    description=f"{kind}: {payload.get('reason', 'No reason')}",
                    evidence=payload,
                    timestamp=timezone.now()
                )
        except Exception as e:
            print(f"Database logging error: {e}")

        return JsonResponse({'status': 'ok'})

    except Exception as e:
        print(f"Log event error: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@login_required
def upload_snapshot(request):
    """Upload proctoring snapshot"""
    try:
        data = json.loads(request.body.decode("utf-8")) or {}
        data_url = data.get('image')
        reason = data.get('reason', 'snapshot')

        if not data_url:
            return JsonResponse({'status': 'error', 'message': 'no image'}, status=400)

        try:
            header, b64 = data_url.split(',', 1)
            ext = 'png' if 'png' in header else 'jpg'
            ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")

            # Categorize snapshots based on reason
            if 'device' in reason.lower() or 'phone' in reason.lower() or 'laptop' in reason.lower():
                folder = 'devices'
                # Sanitize filename
                safe_reason = "".join(
                    c for c in reason if c.isalnum() or c in (' ', '-', '_')).rstrip()
                fname = f'evidence/{folder}/device_detection_{safe_reason}_{ts}.{ext}'
            elif 'suspend' in reason.lower():
                folder = 'snapshots/suspensions'
                fname = f'evidence/{folder}/suspend_{ts}.{ext}'
            elif 'warning' in reason.lower():
                folder = 'snapshots/warnings'
                fname = f'evidence/{folder}/warning_{ts}.{ext}'
            else:
                folder = 'snapshots'
                fname = f'evidence/{folder}/{reason}_{ts}.{ext}'

            # Ensure directory exists
            os.makedirs(os.path.dirname(fname), exist_ok=True)

            with open(fname, 'wb') as f:
                f.write(base64.b64decode(b64))

            print(f'Saved snapshot: {fname}')

            # Log snapshot metadata
            snapshot_log = {
                'type': 'snapshot',
                'reason': reason,
                'file_path': fname,
                'timestamp': ts,
                'detection_type': 'device' if 'device' in reason.lower() else 'general'
            }

            log_fname = f'evidence/logs/snapshot_{ts}.json'
            with open(log_fname, 'w', encoding='utf-8') as f:
                json.dump(snapshot_log, f, ensure_ascii=False, indent=2)

            # Also save to database if we have a transcript
            try:
                transcript_id = request.session.get("transcript_id")
                if transcript_id and transcript_id != "session_only":
                    tr = InterviewTranscript.objects.get(id=transcript_id)
                    ProctorSnapshot.objects.create(
                        interview=tr,
                        image_data=fname,
                        violation_type=data.get('violation_type', 'general'),
                        description=reason,
                        timestamp=timezone.now()
                    )
            except Exception as e:
                print(f"Database snapshot save error: {e}")

            return JsonResponse({'status': 'ok', 'path': fname, 'category': folder})

        except Exception as e:
            print(f'Error processing snapshot: {e}')
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    except Exception as e:
        print(f"Upload snapshot error: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def proctoring_stats(request):
    """Get proctoring statistics"""
    try:
        stats = {
            'total_warnings': 0,
            'warnings_by_type': {},
            'suspensions': 0,
            'device_detections': 0,
            'snapshots': 0
        }

        # Count log files
        if os.path.exists('evidence/logs'):
            for fname in os.listdir('evidence/logs'):
                if fname.startswith('warning_'):
                    stats['total_warnings'] += 1
                    # Extract warning type from filename
                    parts = fname.split('_')
                    if len(parts) > 2:
                        warning_type = parts[1]
                        stats['warnings_by_type'][warning_type] = stats['warnings_by_type'].get(
                            warning_type, 0) + 1
                elif fname.startswith('suspend_'):
                    stats['suspensions'] += 1

        # Count device detections
        if os.path.exists('evidence/devices'):
            stats['device_detections'] = len([f for f in os.listdir('evidence/devices')
                                              if f.startswith('device_detection')])

        # Count snapshots
        for root, dirs, files in os.walk('evidence/snapshots'):
            stats['snapshots'] += len(
                [f for f in files if f.endswith(('.jpg', '.png'))])

        return JsonResponse(stats)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def proctoring_events(request):
    """Get recent proctoring events"""
    try:
        events = []

        # Get recent log files (sorted by modification time)
        log_files = []
        for root, dirs, files in os.walk('evidence'):
            for file in files:
                if file.endswith('.json'):
                    full_path = os.path.join(root, file)
                    log_files.append((full_path, os.path.getmtime(full_path)))

        # Sort by modification time (newest first) and take top 50
        log_files.sort(key=lambda x: x[1], reverse=True)

        for file_path, _ in log_files[:50]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    event_data = json.load(f)
                    event_data['file'] = file_path
                    events.append(event_data)
            except:
                continue

        return JsonResponse(events, safe=False)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def proctoring_status(request):
    """Basic proctoring status endpoint"""
    return JsonResponse({
        'status': 'running',
        'timestamp': datetime.utcnow().isoformat(),
        'evidence_folders': {
            'logs': len(os.listdir('evidence/logs')) if os.path.exists('evidence/logs') else 0,
            'snapshots': len(os.listdir('evidence/snapshots')) if os.path.exists('evidence/snapshots') else 0,
            'devices': len(os.listdir('evidence/devices')) if os.path.exists('evidence/devices') else 0
        }
    })

@csrf_exempt
@login_required
def proctor_violation(request):
    """Handle proctoring violation"""
    try:
        data = json.loads(request.body.decode("utf-8"))
        violation_type = data.get("type", "unknown")
        reason = data.get("reason", "No reason provided")
        evidence_data = data.get("evidence", {})

        print(f"🚨 PROCTORING VIOLATION: {violation_type} - {reason}")

        # Critical violations that cause immediate suspension
        critical_violations = ['multiple_faces', 'no_face',
                               'device', 'tab_absence', 'copy_attempt']

        # Suspend interview for critical violations
        if violation_type in critical_violations:
            suspend_interview_session(
                request, f"Critical proctoring violation: {violation_type} - {reason}")

        # Log the violation using the new system
        log_data = {
            'type': 'warning',
            'kind': violation_type,
            'reason': reason,
            'evidence': evidence_data,
            'critical': violation_type in critical_violations
        }

        return log_event(request._request)  # Use the new logging system

    except Exception as e:
        print(f"Proctor violation error: {e}")
        return JsonResponse({"error": str(e)}, status=500)

# =====================================================
# UPDATED INTERVIEW COMPLETION HANDLING
# =====================================================

@csrf_exempt
@login_required
def end_interview(request):
    """Properly end interview and generate comprehensive final report"""
    try:
        transcript_id = request.session.get("transcript_id")
        final_score = 0
        final_report = ""

        if transcript_id and transcript_id != "session_only":
            tr = InterviewTranscript.objects.get(id=transcript_id)
            tr.completed = True
            
            # Calculate final score
            final_score = calculate_final_score(tr.conversation_history)
            tr.final_score = final_score
            
            # Generate comprehensive final report
            final_report = generate_comprehensive_report(tr.conversation_history, final_score)
            tr.final_report = final_report
            
            # Calculate duration
            if tr.created_at:
                duration = (timezone.now() - tr.created_at).total_seconds() / 60
                tr.duration = int(duration)
            
            tr.save()
            print(f"✅ Interview completed with final score: {final_score}/10")
            print(f"📄 Report generated: {len(final_report)} characters")

        complete_interview_session(request)
        clear_interview_session(request)
        
        return JsonResponse({
            "status": "success", 
            "message": "Interview ended successfully",
            "final_score": final_score,
            "final_report": final_report
        })

    except Exception as e:
        print(f"❌ End interview error: {e}")
        return JsonResponse({"error": str(e)}, status=500)