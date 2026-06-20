import { Component, inject, computed } from '@angular/core';
import { NavbarComponent } from '../../shared/navbar/navbar.component';
import { BuilderStateService } from '../../core/builder-state.service';
import { DataModel, ModelField, ModelRelationship, FieldType } from '../../models/app-spec.model';

const SQL_TYPE: Record<FieldType, (f: ModelField) => string> = {
  string:   f => `VARCHAR(${f.max_length ?? 200})`,
  text:     _ => 'TEXT',
  int:      _ => 'INTEGER',
  decimal:  _ => 'DECIMAL(10, 2)',
  bool:     _ => 'BOOLEAN',
  datetime: _ => 'TIMESTAMPTZ',
  json:     _ => 'JSONB',
  file:     _ => 'VARCHAR(255)',
};

export interface SqlColumn {
  name: string;
  sqlType: string;
  nullable: boolean;
  unique: boolean;
  default?: string;
  comment?: string;
}

export interface SqlTable {
  tableName: string;
  modelName: string;
  description: string;
  columns: SqlColumn[];
  fkConstraints: string[];
  m2mTables: { name: string; ddl: string }[];
}

function toSnake(s: string): string {
  return s.replace(/([A-Z])/g, m => `_${m.toLowerCase()}`).replace(/^_/, '');
}

function buildTable(model: DataModel, allModels: DataModel[]): SqlTable {
  const tableName = toSnake(model.name);
  const columns: SqlColumn[] = [
    { name: 'id', sqlType: 'SERIAL', nullable: false, unique: true, comment: 'Clé primaire' },
  ];
  const fkConstraints: string[] = [];
  const m2mTables: { name: string; ddl: string }[] = [];

  for (const f of model.fields) {
    columns.push({
      name: f.name,
      sqlType: SQL_TYPE[f.type](f),
      nullable: !f.required,
      unique: f.unique,
      default: f.default,
    });
  }

  for (const rel of model.relationships) {
    const targetTable = toSnake(rel.to_model);
    const onDel = rel.on_delete ?? 'CASCADE';

    if (rel.rel_type === 'FK') {
      const colName = `${rel.name}_id`;
      columns.push({ name: colName, sqlType: 'INTEGER', nullable: true, unique: false, comment: `FK → ${rel.to_model}` });
      fkConstraints.push(
        `CONSTRAINT fk_${tableName}_${rel.name} FOREIGN KEY (${colName}) REFERENCES ${targetTable}(id) ON DELETE ${onDel}`
      );
    } else if (rel.rel_type === 'O2O') {
      const colName = `${rel.name}_id`;
      columns.push({ name: colName, sqlType: 'INTEGER', nullable: true, unique: true, comment: `O2O → ${rel.to_model}` });
      fkConstraints.push(
        `CONSTRAINT fk_${tableName}_${rel.name} FOREIGN KEY (${colName}) REFERENCES ${targetTable}(id) ON DELETE ${onDel}`
      );
    } else if (rel.rel_type === 'M2M') {
      const junctionName = `${tableName}_${targetTable}`;
      m2mTables.push({
        name: junctionName,
        ddl: [
          `CREATE TABLE ${junctionName} (`,
          `  ${tableName}_id INTEGER NOT NULL REFERENCES ${tableName}(id) ON DELETE CASCADE,`,
          `  ${targetTable}_id INTEGER NOT NULL REFERENCES ${targetTable}(id) ON DELETE CASCADE,`,
          `  PRIMARY KEY (${tableName}_id, ${targetTable}_id)`,
          `);`,
        ].join('\n'),
      });
    }
  }

  return { tableName, modelName: model.name, description: model.description, columns, fkConstraints, m2mTables };
}

@Component({
  selector: 'app-infra-page',
  standalone: true,
  imports: [NavbarComponent],
  templateUrl: './infra.component.html',
  styleUrl: './infra.component.scss',
})
export class InfraPageComponent {
  state = inject(BuilderStateService);

  tables = computed<SqlTable[]>(() => {
    const models = this.state.spec().data_models;
    return models.map(m => buildTable(m, models));
  });

  ddlFor(table: SqlTable): string {
    const lines: string[] = [`CREATE TABLE ${table.tableName} (`];
    table.columns.forEach((col, i) => {
      const isLast = i === table.columns.length - 1 && table.fkConstraints.length === 0;
      const nullable = col.name === 'id' ? ' PRIMARY KEY' : (col.nullable ? '' : ' NOT NULL');
      const unique   = col.unique && col.name !== 'id' ? ' UNIQUE' : '';
      const def      = col.default ? ` DEFAULT '${col.default}'` : '';
      lines.push(`  ${col.name} ${col.sqlType}${nullable}${unique}${def}${isLast ? '' : ','}`);
    });
    table.fkConstraints.forEach((fk, i) => {
      const isLast = i === table.fkConstraints.length - 1;
      lines.push(`  ${fk}${isLast ? '' : ','}`);
    });
    lines.push(');');
    return lines.join('\n');
  }

  allDdl(): string {
    const parts: string[] = [];
    for (const t of this.tables()) {
      parts.push(this.ddlFor(t));
      for (const m2m of t.m2mTables) {
        parts.push(m2m.ddl);
      }
    }
    return parts.join('\n\n');
  }

  toSnake(s: string): string { return toSnake(s.trim()); }

  copyDdl(): void {
    navigator.clipboard.writeText(this.allDdl());
  }
}
