from django.urls import path
from .handoff import GraphView, HandoffKitView, HandoffSpecDetailView, HandoffSpecListView, LivrablesView
from .mcp import McpInfoView, McpTokenDetailView, McpTokenListCreateView, McpView
from .views import (
    MeView,
    AppSpecListCreateView, AppSpecDetailView,
    AppSpecChatHistoryView,
    AppSpecPatchView, AppSpecPatchHistoryView, AppSpecPatchUndoView,
    AppSpecLabView, AppSpecOperationsView, AppSpecOperationsEssaiView,
    AIChatView, AiKeysView, AiSettingsView, ChatEstimateView, ModelsView,
)

urlpatterns = [
    path('me/',                      MeView.as_view()),
    path('apps/',                    AppSpecListCreateView.as_view()),
    path('apps/<int:pk>/',           AppSpecDetailView.as_view()),
    path('apps/<int:pk>/chat/',      AppSpecChatHistoryView.as_view()),
    path('apps/<int:pk>/patch/',     AppSpecPatchView.as_view()),
    path('apps/<int:pk>/patches/',   AppSpecPatchHistoryView.as_view()),
    path('apps/<int:pk>/patches/<int:application_pk>/undo/', AppSpecPatchUndoView.as_view()),
    path('apps/<int:pk>/operations/',        AppSpecOperationsView.as_view()),
    path('apps/<int:pk>/operations/essai/',  AppSpecOperationsEssaiView.as_view()),
    path('apps/<int:pk>/lab/',       AppSpecLabView.as_view()),
    path('apps/<int:pk>/livrables/', LivrablesView.as_view()),
    path('apps/<int:pk>/graph/',     GraphView.as_view()),
    path('handoff/specs/',                   HandoffSpecListView.as_view()),
    path('handoff/specs/<int:pk>/',          HandoffSpecDetailView.as_view()),
    path('handoff/specs/<int:pk>/kit/',      HandoffKitView.as_view()),
    path('models/',                  ModelsView.as_view()),
    path('chat/estimate/',           ChatEstimateView.as_view()),
    path('chat/',                    AIChatView.as_view()),
    path('ai-keys/',                 AiKeysView.as_view()),
    path('ai-settings/',             AiSettingsView.as_view()),
    path('mcp-tokens/',              McpTokenListCreateView.as_view()),
    path('mcp-tokens/<int:pk>/',     McpTokenDetailView.as_view()),
    path('mcp/info/',                McpInfoView.as_view()),
    path('mcp/',                     McpView.as_view()),
]
