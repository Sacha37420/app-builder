import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./pages/builder/builder.component').then(m => m.BuilderComponent),
  },
  {
    path: 'models',
    loadComponent: () => import('./pages/models/models.component').then(m => m.ModelsPageComponent),
  },
  {
    path: 'endpoints',
    loadComponent: () => import('./pages/endpoints/endpoints.component').then(m => m.EndpointsPageComponent),
  },
  {
    path: 'pages-config',
    loadComponent: () => import('./pages/pages-config/pages-config.component').then(m => m.PagesPageComponent),
  },
  {
    path: 'pipelines',
    loadComponent: () => import('./pages/pipelines/pipelines.component').then(m => m.PipelinesPageComponent),
  },
  {
    path: 'infra',
    loadComponent: () => import('./pages/infra/infra.component').then(m => m.InfraPageComponent),
  },
  {
    path: 'preview',
    loadComponent: () => import('./pages/preview/preview.component').then(m => m.PreviewPageComponent),
  },
  { path: '**', redirectTo: '' },
];
