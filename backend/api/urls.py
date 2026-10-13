from django.urls import path
from .handoff import HandoffKitView, HandoffSpecDetailView, HandoffSpecListView, LivrablesView
from .views import (
    MeView,
    AppSpecListCreateView, AppSpecDetailView,
    AppSpecChatHistoryView,
    AppSpecPatchView, AppSpecPatchHistoryView, AppSpecPatchUndoView,
    AppSpecLabView,
    AIChatView,
)

urlpatterns = [
    path('me/',                      MeView.as_view()),
    path('apps/',                    AppSpecListCreateView.as_view()),
    path('apps/<int:pk>/',           AppSpecDetailView.as_view()),
    path('apps/<int:pk>/chat/',      AppSpecChatHistoryView.as_view()),
    path('apps/<int:pk>/patch/',     AppSpecPatchView.as_view()),
    path('apps/<int:pk>/patches/',   AppSpecPatchHistoryView.as_view()),
    path('apps/<int:pk>/patches/<int:application_pk>/undo/', AppSpecPatchUndoView.as_view()),
    path('apps/<int:pk>/lab/',       AppSpecLabView.as_view()),
    path('apps/<int:pk>/livrables/', LivrablesView.as_view()),
    path('handoff/specs/',                   HandoffSpecListView.as_view()),
    path('handoff/specs/<int:pk>/',          HandoffSpecDetailView.as_view()),
    path('handoff/specs/<int:pk>/kit/',      HandoffKitView.as_view()),
    path('chat/',                    AIChatView.as_view()),
]
