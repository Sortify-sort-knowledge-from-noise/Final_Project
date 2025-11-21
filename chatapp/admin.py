from django.contrib import admin
from .models import InterviewTranscript, UserProfile, InterviewTemplate, ProctorSnapshot, ProctorViolation

class InterviewTranscriptAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'created_at', 'role', 'completed', 'final_score']
    readonly_fields = ['created_at', 'updated_at']
    list_filter = ['completed', 'created_at']
    search_fields = ['user__username', 'role']

class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'user_type', 'company']
    list_filter = ['user_type']
    search_fields = ['user__username', 'company']

class InterviewTemplateAdmin(admin.ModelAdmin):
    list_display = ['title', 'role', 'difficulty', 'created_by', 'created_at']
    list_filter = ['difficulty', 'created_at']
    search_fields = ['title', 'role', 'created_by__username']

admin.site.register(InterviewTranscript, InterviewTranscriptAdmin)
admin.site.register(UserProfile, UserProfileAdmin)
admin.site.register(InterviewTemplate, InterviewTemplateAdmin)
admin.site.register(ProctorSnapshot)
admin.site.register(ProctorViolation)