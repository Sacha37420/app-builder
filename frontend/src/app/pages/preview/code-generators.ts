import {
  AppSpec, DataModel, ModelField, EndpointGroup, Endpoint,
  FrontendService, Page, DJANGO_FIELD_MAP, TS_FIELD_MAP,
} from '../../models/app-spec.model';

function toSnake(s: string): string {
  return s.replace(/([A-Z])/g, '_$1').toLowerCase().replace(/^_/, '');
}

function indent(s: string, n = 4): string {
  return s.split('\n').map(l => ' '.repeat(n) + l).join('\n');
}

// ── models.py ─────────────────────────────────────────────────────────────────

function djFieldLine(f: ModelField): string {
  let ftype = DJANGO_FIELD_MAP[f.type].replace('{len}', String(f.max_length ?? 200));
  const opts: string[] = [];
  if (!f.required) opts.push('blank=True', 'null=True');
  if (f.unique) opts.push('unique=True');
  if (f.default !== undefined && f.default !== '') opts.push(`default=${JSON.stringify(f.default)}`);
  if (opts.length) {
    ftype = ftype.replace(')', `, ${opts.join(', ')})`);
  }
  return `${toSnake(f.name)} = ${ftype}`;
}

function djRelLine(rel: { name: string; rel_type: string; to_model: string; related_name: string; on_delete?: string }): string {
  const cls = { FK: 'ForeignKey', M2M: 'ManyToManyField', O2O: 'OneToOneField' }[rel.rel_type as 'FK' | 'M2M' | 'O2O'] ?? 'ForeignKey';
  const args = [`'${rel.to_model}'`];
  if (rel.rel_type !== 'M2M') args.push(`on_delete=models.${rel.on_delete ?? 'CASCADE'}`);
  if (rel.related_name) args.push(`related_name='${rel.related_name}'`);
  return `${toSnake(rel.name)} = models.${cls}(${args.join(', ')})`;
}

export function generateModelsPy(spec: AppSpec): string {
  if (spec.data_models.length === 0) return '# Aucun modèle défini (Phase 1 incomplète)\n';

  const lines: string[] = [
    'from django.db import models\n',
  ];

  for (const m of spec.data_models) {
    lines.push(`\nclass ${m.name}(models.Model):`);
    if (m.description) lines.push(indent(`"""${m.description}"""`));
    for (const f of m.fields) lines.push(indent(djFieldLine(f)));
    for (const r of m.relationships) lines.push(indent(djRelLine(r)));
    if (m.fields.length === 0 && m.relationships.length === 0) lines.push(indent('pass'));
    lines.push('');
    lines.push(indent(`class Meta:`));
    lines.push(indent(`db_table = '${toSnake(m.name)}s'`, 8));
    lines.push('');
  }

  return lines.join('\n');
}

// ── serializers.py ────────────────────────────────────────────────────────────

export function generateSerializersPy(spec: AppSpec): string {
  if (spec.data_models.length === 0) return '# Aucun modèle défini (Phase 1 incomplète)\n';

  const names = spec.data_models.map(m => m.name);
  const lines: string[] = [
    'from rest_framework import serializers',
    `from .models import ${names.join(', ')}\n`,
  ];

  for (const m of spec.data_models) {
    const fields = [
      ...m.fields.map(f => `'${toSnake(f.name)}'`),
      ...m.relationships.map(r => `'${toSnake(r.name)}'`),
    ];
    lines.push(`\nclass ${m.name}Serializer(serializers.ModelSerializer):`);
    lines.push(indent(`class Meta:`));
    lines.push(indent(`model = ${m.name}`, 8));
    lines.push(indent(`fields = ['id'${fields.length ? ', ' + fields.join(', ') : ''}]`, 8));
    lines.push('');
  }

  return lines.join('\n');
}

// ── views.py ──────────────────────────────────────────────────────────────────

export function generateViewsPy(spec: AppSpec): string {
  if (spec.endpoint_groups.length === 0) return '# Aucun endpoint défini (Phase 2 incomplète)\n';

  const modelNames = spec.data_models.map(m => m.name);
  const usedModels = new Set<string>();
  const usedSerializers = new Set<string>();

  const viewLines: string[] = [];

  for (const group of spec.endpoint_groups) {
    for (const ep of group.endpoints) {
      if (ep.linked_model_name) {
        usedModels.add(ep.linked_model_name);
        usedSerializers.add(`${ep.linked_model_name}Serializer`);
      }

      const viewName = `${group.name.replace(/\s/g, '')}${ep.method[0]}${ep.path.split('/').filter(Boolean).pop()?.replace(/[^a-zA-Z]/g, '') ?? 'View'}View`;
      const baseClass = ep.operation === 'list' ? 'generics.ListAPIView'
        : ep.operation === 'create' ? 'generics.CreateAPIView'
        : ep.operation === 'retrieve' ? 'generics.RetrieveAPIView'
        : ep.operation === 'update' || ep.operation === 'partial_update' ? 'generics.UpdateAPIView'
        : ep.operation === 'delete' ? 'generics.DestroyAPIView'
        : 'APIView';

      viewLines.push(`\nclass ${viewName}(${baseClass}):`);
      viewLines.push(indent(`"""${ep.method} ${ep.path}${ep.description ? ' — ' + ep.description : ''}"""`));
      if (ep.linked_model_name) {
        viewLines.push(indent(`queryset = ${ep.linked_model_name}.objects.all()`));
        viewLines.push(indent(`serializer_class = ${ep.linked_model_name}Serializer`));
      }
      if (!ep.auth_required) {
        viewLines.push(indent(`permission_classes = [AllowAny]`));
      }
      if (ep.operation === 'custom' || !ep.linked_model_name) {
        viewLines.push(indent(`def ${ep.method.toLowerCase()}(self, request):`));
        viewLines.push(indent(`pass  # TODO: implémenter`, 8));
      }
      viewLines.push('');
    }
  }

  const imports = [
    'from rest_framework import generics',
    'from rest_framework.views import APIView',
    'from rest_framework.permissions import IsAuthenticated, AllowAny',
  ];
  if (usedModels.size) imports.push(`from .models import ${[...usedModels].join(', ')}`);
  if (usedSerializers.size) imports.push(`from .serializers import ${[...usedSerializers].join(', ')}`);

  return [...imports, ...viewLines].join('\n');
}

// ── urls.py ───────────────────────────────────────────────────────────────────

export function generateUrlsPy(spec: AppSpec): string {
  if (spec.endpoint_groups.length === 0) return '# Aucun endpoint défini\n';

  const viewNames: string[] = [];
  const urlEntries: string[] = [];

  for (const group of spec.endpoint_groups) {
    for (const ep of group.endpoints) {
      const vn = `${group.name.replace(/\s/g, '')}${ep.method[0]}${ep.path.split('/').filter(Boolean).pop()?.replace(/[^a-zA-Z]/g, '') ?? 'View'}View`;
      viewNames.push(vn);
      urlEntries.push(`    path('${ep.path.replace(/^\//, '')}', ${vn}.as_view()),`);
    }
  }

  return [
    'from django.urls import path',
    `from .views import ${viewNames.join(', ')}\n`,
    'urlpatterns = [',
    ...urlEntries,
    ']',
  ].join('\n');
}

// ── *.service.ts ──────────────────────────────────────────────────────────────

export function generateServiceTs(spec: AppSpec, svc: FrontendService): string {
  const linkedGroups = spec.endpoint_groups.filter(g => svc.endpoint_group_ids.includes(g.id!));
  const linkedModels = new Set<string>();
  const methods: string[] = [];

  for (const group of linkedGroups) {
    for (const ep of group.endpoints) {
      if (ep.linked_model_name) linkedModels.add(ep.linked_model_name);

      const returnType = ep.linked_model_name
        ? (ep.operation === 'list' ? `${ep.linked_model_name}[]` : ep.linked_model_name)
        : 'unknown';
      const paramName = ep.path.match(/:(\w+)/)?.[1];
      const params = paramName ? `${paramName}: number` : '';
      const bodyParam = ['POST', 'PUT', 'PATCH'].includes(ep.method)
        ? (params ? ', ' : '') + `data: Partial<${ep.linked_model_name || 'unknown'}>`
        : '';

      const methodName = ep.operation === 'list' ? 'getAll'
        : ep.operation === 'create' ? 'create'
        : ep.operation === 'retrieve' ? 'getById'
        : ep.operation === 'update' ? 'update'
        : ep.operation === 'partial_update' ? 'patch'
        : ep.operation === 'delete' ? 'delete'
        : toSnake(ep.path.split('/').filter(Boolean).pop() ?? 'call').replace(/_/g, '');

      const httpMethod = ep.method.toLowerCase();
      const urlExpr = paramName
        ? '`${this.base}' + ep.path.replace(`:${paramName}`, `${paramName}`) + '`'
        : `\`\${this.base}${ep.path}\``;

      methods.push(
        `  /** ${ep.method} ${ep.path}${ep.description ? ' — ' + ep.description : ''} */`,
        `  ${methodName}(${params}${bodyParam}): Observable<${returnType}> {`,
        `    return this.http.${httpMethod}<${returnType}>(${urlExpr}${bodyParam ? ', data' : ''});`,
        `  }`,
        '',
      );
    }
  }

  const modelImports = linkedModels.size
    ? `import { ${[...linkedModels].join(', ')} } from '../models/app-spec.model';\n`
    : '';

  return [
    `import { Injectable, inject } from '@angular/core';`,
    `import { HttpClient } from '@angular/common/http';`,
    `import { Observable } from 'rxjs';`,
    modelImports,
    `@Injectable({ providedIn: 'root' })`,
    `export class ${svc.name} {`,
    `  private http = inject(HttpClient);`,
    `  private base = (window as any).__env?.apiUrl ?? 'http://localhost:8000';`,
    '',
    ...methods,
    '}',
  ].join('\n');
}

// ── component.ts ──────────────────────────────────────────────────────────────

export function generateComponentTs(spec: AppSpec, page: Page): string {
  const usedSvcs = spec.services.filter(s => page.service_ids.includes(s.id!));

  const imports = usedSvcs.map(s => `import { ${s.name} } from '../../core/${toSnake(s.name)}.service';`);
  const injects = usedSvcs.map(s => `  private ${toSnake(s.name).replace(/_service$/, 'Svc')} = inject(${s.name});`);

  const componentName = page.name.replace(/\s/g, '') + 'Component';
  const selector = 'app-' + toSnake(page.name).replace(/_/g, '-');

  return [
    `import { Component, inject, OnInit, signal } from '@angular/core';`,
    ...imports,
    '',
    `@Component({`,
    `  selector: '${selector}',`,
    `  standalone: true,`,
    `  templateUrl: './${toSnake(page.name).replace(/_/g, '-')}.component.html',`,
    `  styleUrl: './${toSnake(page.name).replace(/_/g, '-')}.component.scss',`,
    `})`,
    `export class ${componentName} implements OnInit {`,
    ...injects,
    '',
    `  ngOnInit(): void {`,
    `    // TODO: charger les données initiales`,
    `  }`,
    `}`,
  ].join('\n');
}
