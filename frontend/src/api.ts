import createClient from "openapi-fetch";
import type { components, paths } from "./api.generated";

const client = createClient<paths>({ credentials: "same-origin", cache: "no-store" });

export type User = components["schemas"]["UserOut"];
export type Student = components["schemas"]["StudentOut"];
export type Lesson = components["schemas"]["LessonSummary"];
export type LessonState = components["schemas"]["LessonOut"];
export type LessonResponse = components["schemas"]["LessonResponseIn"];
export type Task = components["schemas"]["TaskOut"];

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

function checked<T>(result: { response: Response; data?: T; error?: { message: string } }): T {
  if (!result.response.ok) {
    throw new ApiError(result.response.status, result.error?.message ?? "Запрос не выполнен.");
  }
  return result.data as T;
}

function account(id: string) {
  return { "X-Expected-Account": id };
}

export const api = {
  async me() {
    return checked(await client.GET("/api/v1/auth/me"));
  },
  async teacher(email: string, password: string) {
    return checked(await client.POST("/api/v1/auth/teacher", { body: { email, password } }));
  },
  async student(token: string) {
    return checked(await client.POST("/api/v1/auth/student", { body: { token } }));
  },
  async logout() {
    checked(await client.POST("/api/v1/auth/logout"));
  },
  async tasks(accountId: string) {
    return checked(await client.GET("/api/v1/tasks", { params: { header: account(accountId) } }));
  },
  async students(accountId: string) {
    return checked(await client.GET("/api/v1/students", { params: { header: account(accountId) } }));
  },
  async lessons(accountId: string) {
    return checked(await client.GET("/api/v1/student/lessons", {
      params: { header: account(accountId) },
    }));
  },
  async openLesson(accountId: string, lesson_id: string) {
    return checked(await client.POST("/api/v1/student/lessons/{lesson_id}/open", {
      params: { path: { lesson_id }, header: account(accountId) },
    }));
  },
  async respondToLesson(accountId: string, lesson_id: string, body: LessonResponse) {
    return checked(await client.POST("/api/v1/student/lessons/{lesson_id}/responses", {
      params: { path: { lesson_id }, header: account(accountId) }, body,
    }));
  },
  async createStudent(accountId: string, name: string) {
    return checked(await client.POST("/api/v1/students", {
      params: { header: account(accountId) }, body: { name },
    }));
  },
  async issueLink(accountId: string, student_id: string) {
    return checked(await client.POST("/api/v1/students/{student_id}/link", {
      params: { path: { student_id }, header: account(accountId) },
    }));
  },
  async revokeLink(accountId: string, student_id: string) {
    checked(await client.DELETE("/api/v1/students/{student_id}/link", {
      params: { path: { student_id }, header: account(accountId) },
    }));
  },
};

export function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "Не удалось связаться с сервером.";
}
