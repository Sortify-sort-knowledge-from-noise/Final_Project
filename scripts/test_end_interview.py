import os
import django
import json
import sys
# Ensure project root is on sys.path (script runs from scripts/ directory)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ollama_chat.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth.models import User
from chatapp.models import InterviewTranscript
from chatapp import views
from datetime import datetime

print('Starting internal end_interview test...')

# Try ORM-based test first, but fall back to directly calling generate_interview_report
try:
    user = User.objects.first()
    if not user:
        print('No users found. Creating test user...')
        user = User.objects.create_user('testuser', 'test@example.com', 'testpass')

    # Attempt to create a transcript row (may fail if DB schema is out-of-sync)
    conversation = (
        "Candidate: Answer one\n[Score: 8/10 - Excellent]\n\n"
        "Interviewer: Follow-up question\n\n"
        "Candidate: Answer two\n[Score: 6/10 - Good]\n\n"
    )

    try:
        tr = InterviewTranscript.objects.create(
            user=user,
            template=None,
            role='Test Role',
            conversation_history=conversation,
        )
        print(f'Created transcript id={tr.id} (DB test)')

        # Build a fake request and attach session
        rf = RequestFactory()
        req = rf.post('/end_interview/')
        req.user = user
        middleware = SessionMiddleware()
        middleware.process_request(req)
        req.session['transcript_id'] = tr.id
        req.session.save()

        resp = views.end_interview(req)
        print('end_interview view status:', getattr(resp, 'status_code', 'N/A'))
        try:
            print(resp.content.decode()[:2000])
        except Exception:
            print(resp)

        tr.refresh_from_db()
        print('Transcript final_score (DB):', tr.final_score)
        print('Transcript final_report length (DB):', len(tr.final_report) if tr.final_report else 0)

    except Exception as db_e:
        print('DB-based test failed:', db_e)
        print('Falling back to direct report generation call (no DB operations).')

        # Create a minimal dummy transcript-like object
        class DummyUser:
            def __init__(self, username):
                self.username = username

        class DummyTranscript:
            def __init__(self, username, role, conversation):
                self.user = DummyUser(username)
                self.role = role
                self.conversation_history = conversation
                from datetime import datetime
                self.created_at = datetime.now()

        dummy = DummyTranscript('testuser', 'Test Role', conversation)

        # Call the report generator directly
        report_data = views.generate_interview_report(dummy)
        print('Generated report keys:', list(report_data.keys()))
        print('Final score:', report_data.get('final_score'))
        print('Report HTML length:', len(report_data.get('report_html', '')))

except Exception as e:
    print('Fatal test error:', e)

print('Internal test complete.')
