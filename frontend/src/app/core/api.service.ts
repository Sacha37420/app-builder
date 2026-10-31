import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { apiUrl } from './env';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  private get base(): string {
    return apiUrl();
  }

  getMe(): Observable<unknown> {
    return this.http.get(`${this.base}/api/me/`);
  }
}
