import { useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "./api";
import type { CabinetResult, StudentResult } from "./api";

type Who = "teacher" | "student";

const labels: Record<string, string> = {
  summary: "Конспект",
  key_concepts: "Ключевые понятия",
  text: "Текст",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fileOf(value: unknown): { id: string; name: string } | null {
  const file = isRecord(value) && isRecord(value.file) ? value.file : value;
  if (isRecord(file) && typeof file.id === "string" && typeof file.name === "string" && typeof file.media_type === "string") {
    return { id: file.id, name: file.name };
  }
  return null;
}

function Value({ value }: { value: unknown }) {
  if (typeof value === "string") return <p className="lesson-text">{value}</p>;
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return <ul>{value.map((item, index) => <li key={index}>{item}</li>)}</ul>;
  }
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

export function ResultContent({ content, who }: { content: unknown; who: Who }) {
  const file = fileOf(content);
  if (file) {
    // Файл скачивает только преподаватель: ученику его файлы не отдаются.
    return who === "teacher"
      ? <p><a href={`/api/v1/files/${encodeURIComponent(file.id)}/content`} download={file.name}>Скачать {file.name}</a></p>
      : <p>Файл: {file.name}</p>;
  }
  if (isRecord(content)) {
    return (
      <dl>
        {Object.entries(content).map(([name, value]) => (
          <div key={name}>
            <dt>{labels[name] ?? name}</dt>
            <dd><Value value={value} /></dd>
          </div>
        ))}
      </dl>
    );
  }
  return <Value value={content} />;
}

export function CabinetResults({ accountId, who, onSessionChange }: {
  accountId: string;
  who: Who;
  onSessionChange: () => void;
}) {
  const [results, setResults] = useState<(CabinetResult | StudentResult)[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const load = who === "teacher" ? api.teacherResults(accountId) : api.studentResults(accountId);
    load
      .then((list) => { if (active) setResults(list); })
      .catch((failure: unknown) => {
        if (!active) return;
        if (failure instanceof ApiError && [401, 403, 409].includes(failure.status)) onSessionChange();
        else setError(errorMessage(failure));
      })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [accountId, who, onSessionChange]);

  return (
    <section>
      <h2>{who === "teacher" ? "Результаты" : "Мои результаты"}</h2>
      {error && <p role="alert">{error}</p>}
      {!busy && !error && results.length === 0 && <p>Результатов пока нет.</p>}
      <ul className="results">
        {results.map((result) => (
          <li key={result.id}>
            <h3>{result.title}</h3>
            <p className="result-meta">
              {new Date(result.created_at).toLocaleString("ru-RU")}
              {"student_name" in result && result.student_name && ` · для ученика ${result.student_name}`}
            </p>
            <ResultContent content={result.content} who={who} />
          </li>
        ))}
      </ul>
    </section>
  );
}
