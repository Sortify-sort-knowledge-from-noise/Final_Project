from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class UserProfile(models.Model):
    USER_TYPE_CHOICES = [
        ('candidate', 'Candidate'),
        ('recruiter', 'Recruiter'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='candidate')
    company = models.CharField(max_length=200, blank=True, null=True)
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.user_type}"

class InterviewTemplate(models.Model):
    DIFFICULTY_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
    ]
    
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_templates')
    title = models.CharField(max_length=200)
    role = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='intermediate')
    duration = models.IntegerField(default=30)  # in minutes
    topics = models.JSONField(default=list)  # List of topics/questions
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.role}"

class InterviewTranscript(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='interview_transcripts')
    template = models.ForeignKey(InterviewTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=200, default='C Developer')
    conversation_history = models.TextField(blank=True)
    final_report = models.TextField(blank=True)
    final_score = models.FloatField(null=True, blank=True)
    duration = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.role} - {self.created_at}"

class ProctorSnapshot(models.Model):
    interview = models.ForeignKey(InterviewTranscript, on_delete=models.CASCADE, related_name='snapshots')
    image_data = models.TextField()
    violation_type = models.CharField(max_length=100)
    timestamp = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return f"Snapshot - {self.interview.id} - {self.violation_type}"

class ProctorViolation(models.Model):
    interview = models.ForeignKey(InterviewTranscript, on_delete=models.CASCADE, related_name='violations')
    violation_type = models.CharField(max_length=100)
    description = models.TextField()
    evidence = models.JSONField(default=dict)
    timestamp = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return f"Violation - {self.interview.id} - {self.violation_type}"