from django.urls import path
from .views import (
    MeView,
    AppSpecListCreateView, AppSpecDetailView, AppSpecPublicView,
    InfrastructureView,
    AIChatView,
)

urlpatterns = [
    path('me/',              MeView.as_view()),
    path('apps/',            AppSpecListCreateView.as_view()),
    path('apps/public/',     AppSpecPublicView.as_view()),
    path('apps/<int:pk>/',   AppSpecDetailView.as_view()),
    path('infrastructure/',  InfrastructureView.as_view()),
    path('chat/',            AIChatView.as_view()),
]
