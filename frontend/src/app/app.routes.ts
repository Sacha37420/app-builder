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
    path: 'pipelines',
    loadComponent: () => import('./pages/pipelines/pipelines.component').then(m => m.PipelinesPageComponent),
  },
  {
    path: 'preview',
    loadComponent: () => import('./pages/preview/preview.component').then(m => m.PreviewPageComponent),
  },
  {
    path: 'profile',
    loadComponent: () => import('./pages/profile/profile.component').then(m => m.ProfileComponent),
  },
  { path: '**', redirectTo: '' },
];
