import json
import requests as http_requests
from decouple import config as env_config
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import generics, status
from rest_framework.response import Response
from .models import AppSpec
from .serializers import AppSpecSerializer


class MeView(APIView):
    def get(self, request):
        return Response({
            'email':    request.user.email,
            'username': request.user.username,
            'groups':   request.user.claims.get('groups', []),
        })


class AppSpecListCreateView(generics.ListCreateAPIView):
    serializer_class = AppSpecSerializer

    def get_queryset(self):
        return AppSpec.objects.filter(owner_email=self.request.user.email)

    def perform_create(self, serializer):
        serializer.save(owner_email=self.request.user.email)


class AppSpecDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AppSpecSerializer

    def get_queryset(self):
        return AppSpec.objects.filter(owner_email=self.request.user.email)


class AIChatView(APIView):
    """POST /api/chat/ — proxy vers Mistral ou Claude avec contexte app spec."""

    def post(self, request):
        provider = request.data.get('provider', 'claude')
        api_key = request.data.get('api_key') or env_config(
            'MISTRAL_API_KEY' if provider == 'mistral' else 'ANTHROPIC_API_KEY',
            default='',
        )
        messages = request.data.get('messages', [])
        app_spec = request.data.get('app_spec', {})

        if not api_key:
            return Response(
                {'error': f'Clé API {provider} manquante'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        system_prompt = (
            "Tu es un assistant expert en architecture logicielle fullstack (Django + Angular). "
            "Tu aides l'utilisateur à concevoir son application en détaillant :\n"
            "- Les endpoints API backend (méthodes, chemins, descriptions)\n"
            "- Les services Angular et les pages frontend\n"
            "- Les interactions utilisateur par page\n"
            "- Les pipelines de données\n\n"
            "Pose des questions précises pour clarifier les points flous. "
            "Suggère des améliorations architecturales. "
            "Chaque réponse doit pousser l'utilisateur vers une spécification plus complète.\n\n"
            f"Application en cours de conception :\n{json.dumps(app_spec, ensure_ascii=False, indent=2)}"
        )

        try:
            if provider == 'mistral':
                return self._call_mistral(api_key, system_prompt, messages)
            else:
                return self._call_claude(api_key, system_prompt, messages)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    def _call_mistral(self, api_key, system_prompt, messages):
        payload = {
            'model': 'mistral-small-latest',
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
        }
        resp = http_requests.post(
            'https://api.mistral.ai/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data['choices'][0]['message']['content']
        return Response({'content': content, 'provider': 'mistral'})

    def _call_claude(self, api_key, system_prompt, messages):
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        content = msg.content[0].text
        return Response({'content': content, 'provider': 'claude'})
