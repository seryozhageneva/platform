import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError, errorMessage } from "./api";

type Column = { key: string; title: string; editable?: boolean };
type Table = { columns: Column[]; rows: Record<string, unknown>[] };

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function column(value: unknown): value is Column {
  return record(value) && typeof value.key === "string" && typeof value.title === "string" &&
    (value.editable === undefined || typeof value.editable === "boolean");
}

export function reviewTable(data: Record<string, unknown>): Table | undefined {
  const { columns, rows } = data;
  if (Array.isArray(columns) && columns.every(column) && Array.isArray(rows) && rows.every(record)) {
    return { columns, rows };
  }
}

function display(value: unknown) {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

export function ApprovalTable({
  table, accountId, runId, nodeId, approvalId, onRefresh, onSessionChange,
}: {
  table: Table; accountId: string; runId: string; nodeId: string; approvalId: string;
  onRefresh: (notice: string) => void; onSessionChange: () => void;
}) {
  const [skipped, setSkipped] = useState<Record<number, boolean>>({});
  const [edits, setEdits] = useState<Record<number, Record<string, string>>>({});
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState("");
  const sending = useRef(false);
  const kept = table.rows.filter((_, index) => !skipped[index]).length;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (sending.current) return;
    sending.current = true;
    setLocked(true);
    setError("");
    try {
      const run = await api.respondToRun(accountId, runId, {
        node_id: nodeId, approval_id: approvalId,
        response: { rows: table.rows.map((row, index) => ({
          index, keep: !skipped[index],
          values: skipped[index] ? {} : Object.fromEntries(
            Object.entries(edits[index] ?? {}).filter(([key, value]) => row[key] !== value),
          ),
        })) },
      });
      onRefresh(run.status === "error" ? "Запуск остановился с ошибкой. Подробности в журнале." : "Решение принято.");
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) {
        onSessionChange();
        onRefresh("Таблица уже обновляется или решение принято. Данные загружаются заново.");
        // После обновления при той же паузе можно повторить запрос с теми же правками.
      } else {
        if (failure instanceof ApiError && [401, 403].includes(failure.status)) onSessionChange();
        setError(errorMessage(failure));
      }
      sending.current = false;
      setLocked(false);
    }
  }

  return <form aria-label="Таблица подтверждения" onSubmit={(event) => { void submit(event); }}>
    <fieldset disabled={locked}>
      <legend>Подтверждение преподавателем</legend>
      <div className="approval-scroll">
        <table>
          <thead><tr><th scope="col">Строка</th>
            {table.columns.map(({ key, title }) => <th key={key} scope="col">{title}</th>)}
            <th scope="col">Решение</th>
          </tr></thead>
          <tbody>{table.rows.map((row, index) => <tr key={index}>
            <th scope="row">{index + 1}</th>
            {table.columns.map(({ key, title, editable }) => {
              const value = Object.hasOwn(row, key) ? row[key] : undefined;
              return <td key={key}>
                {editable && typeof value === "string"
                  ? <textarea aria-label={`${title}, строка ${index + 1}`} disabled={skipped[index]}
                    value={edits[index]?.[key] ?? value} onChange={(event) => {
                      const next = event.target.value;
                      setEdits((current) => ({ ...current, [index]: { ...current[index], [key]: next } }));
                    }} />
                  : display(value)}
              </td>;
            })}
            <td><label><input type="checkbox" checked={!!skipped[index]} onChange={(event) => {
              const checked = event.target.checked;
              setSkipped((current) => ({ ...current, [index]: checked }));
            }} />Пропустить строку {index + 1}</label></td>
          </tr>)}</tbody>
        </table>
      </div>
      <p aria-live="polite">Строк пойдёт дальше: {kept} из {table.rows.length}.</p>
      <button type="submit">{kept ? "Подтвердить" : "Отклонить все строки"}</button>
    </fieldset>
    {locked && <p role="status">Отправка решения…</p>}
    {error && <p role="alert">{error}</p>}
  </form>;
}
