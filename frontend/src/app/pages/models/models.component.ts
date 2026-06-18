import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import { DataModel, FieldType, RelType } from '../../models/app-spec.model';
import { NavbarComponent } from '../../shared/navbar/navbar.component';

@Component({
  selector: 'app-models-page',
  standalone: true,
  imports: [FormsModule, NavbarComponent],
  templateUrl: './models.component.html',
  styleUrl: './models.component.scss',
})
export class ModelsPageComponent {
  state = inject(BuilderStateService);

  expandedModel = signal<number | null>(null);

  readonly fieldTypes: FieldType[] = ['string', 'text', 'int', 'decimal', 'bool', 'datetime', 'json', 'file'];
  readonly relTypes: RelType[] = ['FK', 'M2M', 'O2O'];
  readonly onDeleteChoices = ['CASCADE', 'SET_NULL', 'PROTECT', 'DO_NOTHING'] as const;

  toggle(id: number): void {
    this.expandedModel.update(v => v === id ? null : id);
  }

  isExpanded(id: number): boolean {
    return this.expandedModel() === id;
  }

  djField(type: FieldType, maxLen?: number): string {
    const map: Record<FieldType, string> = {
      string:   `CharField(max_length=${maxLen ?? 200})`,
      text:     'TextField()',
      int:      'IntegerField()',
      decimal:  'DecimalField(max_digits=10, decimal_places=2)',
      bool:     'BooleanField(default=False)',
      datetime: 'DateTimeField()',
      json:     'JSONField(default=dict)',
      file:     'FileField(upload_to="uploads/")',
    };
    return `models.${map[type]}`;
  }

  relLabel(rel: RelType): string {
    return { FK: 'ForeignKey', M2M: 'ManyToManyField', O2O: 'OneToOneField' }[rel];
  }

  val(e: Event): string { return (e.target as HTMLInputElement).value; }
  checked(e: Event): boolean { return (e.target as HTMLInputElement).checked; }

  setModelName(id: number, e: Event): void { this.state.updateDataModel(id, { name: this.val(e) }); }
  setModelDesc(id: number, e: Event): void { this.state.updateDataModel(id, { description: this.val(e) }); }

  setFieldName(mId: number, idx: number, e: Event): void     { this.state.updateField(mId, idx, { name: this.val(e) }); }
  setFieldType(mId: number, idx: number, e: Event): void     { this.state.updateField(mId, idx, { type: this.val(e) as FieldType }); }
  setFieldRequired(mId: number, idx: number, e: Event): void { this.state.updateField(mId, idx, { required: this.checked(e) }); }
  setFieldUnique(mId: number, idx: number, e: Event): void   { this.state.updateField(mId, idx, { unique: this.checked(e) }); }
  setFieldMaxLen(mId: number, idx: number, e: Event): void   { this.state.updateField(mId, idx, { max_length: +this.val(e) }); }
  setFieldDefault(mId: number, idx: number, e: Event): void  { this.state.updateField(mId, idx, { default: this.val(e) || undefined }); }

  setRelName(mId: number, idx: number, e: Event): void        { this.state.updateRelationship(mId, idx, { name: this.val(e) }); }
  setRelType(mId: number, idx: number, e: Event): void        { this.state.updateRelationship(mId, idx, { rel_type: this.val(e) as RelType }); }
  setRelToModel(mId: number, idx: number, e: Event): void     { this.state.updateRelationship(mId, idx, { to_model: this.val(e) }); }
  setRelRelatedName(mId: number, idx: number, e: Event): void { this.state.updateRelationship(mId, idx, { related_name: this.val(e) }); }
  setRelOnDelete(mId: number, idx: number, e: Event): void    { this.state.updateRelationship(mId, idx, { on_delete: this.val(e) as any }); }
}
