from django.urls import path
from . import views

urlpatterns = [
    # Main routes
    path('', views.index_view, name='index_view'),
    path('login/', views.login_view, name='login_view'),
    path('register/', views.register_view, name='register_view'),
    path('logout/', views.logout_view, name='logout_view'),
    path('profile/', views.profile_view, name='profile_view'),
    
    # Interview routes
    path('chat/', views.chat_page, name='chat_page'),
    path('recruiter/', views.recruiter_dashboard, name='recruiter_dashboard'),
    
    # Interview API routes
    path('api/start_interview/', views.start_interview, name='start_interview'),
    path('api/stream_chat/', views.stream_chat, name='stream_chat'),
    path('api/check_time/', views.check_time, name='check_time'),
    
    # Template API routes (FIXED)
    path('api/templates/', views.get_templates, name='get_templates'),
    path('api/available_templates/', views.get_available_templates, name='get_available_templates'),
    path('api/templates/create/', views.create_template, name='create_template'),
    path('api/templates/<int:template_id>/', views.get_template_detail, name='get_template_detail'),
    path('api/templates/<int:template_id>/update/', views.update_template, name='update_template'),
    path('api/templates/<int:template_id>/delete/', views.delete_template, name='delete_template'),
    
    # Proctoring routes (FULL MONITORING)
    path('api/proctor_violation/', views.proctor_violation, name='proctor_violation'),
    path('api/upload_snapshot/', views.upload_snapshot, name='upload_snapshot'),
    # Aliases for legacy frontend paths (some templates use non-`api/` routes)
    path('proctor_violation/', views.proctor_violation, name='proctor_violation_alias'),
    path('upload_snapshot', views.upload_snapshot, name='upload_snapshot_alias'),
    path('end_interview/', views.end_interview, name='end_interview'),
    path('stream_chat/', views.stream_chat, name='stream_chat_alias'),
    path('start_interview/', views.start_interview, name='start_interview_alias'),
]