import { useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "./api";
import type { BlockCatalogItem, Pipeline, PipelineSummary, Problem } from "./api";
import { PipelineCanvas } from "./PipelineCanvas";
import { BlockSettings, PipelineParameters } from "./PipelineSettings";
import { makeBlock, newPipeline, readOnlyReason, removeNode, sameGraph, updateNode } from "./pipelineGraph";

type Session = { accountId: string; onSessionChange: () => void };
type ListItem = Pick<PipelineSummary, "id" | "name" | "latest_version">;
type SavedVersion = { id: string; version: number };
type UncertainSave = { graph: Pipeline; previous: SavedVersion | null };

const categories: Record<BlockCatalogItem["category"], string> = {
  source: "Источники", transform: "Преобразование", student: "Взаимодействие с учеником",
  check: "Проверка", ai_process: "ИИ-обработка", approval: "Подтверждение", sink: "Получатели",
};

function sessionError(error: unknown, refresh: () => void) {
  if (error instanceof ApiError && [401, 403, 409].includes(error.status)) {
    refresh();
    return true;
  }
  return false;
}

export function TeacherPipelines({ accountId, onSessionChange, onPipelineSaved }: Session & {
  onPipelineSaved?: () => void;
}) {
  const [list, setList] = useState<ListItem[]>([]);
  const [editor, setEditor] = useState<{ graph: Pipeline; id?: string; version?: number; catalog: BlockCatalogItem[] }>();
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.pipelines(accountId).then((items) => {
      if (active) setList(items);
    }).catch((failure: unknown) => {
      if (active && !sessionError(failure, onSessionChange)) setError(errorMessage(failure));
    }).finally(() => {
      if (active) setBusy(false);
    });
    return () => { active = false; };
  }, [accountId, onSessionChange]);

  async function open(id?: string) {
    setBusy(true);
    setError("");
    try {
      const [catalog, detail] = await Promise.all([api.blocks(accountId), id ? api.pipeline(accountId, id) : undefined]);
      setEditor(detail
        ? { graph: detail.graph, id: detail.id, version: detail.latest_version, catalog }
        : { graph: newPipeline(), catalog });
    } catch (failure) {
      if (!sessionError(failure, onSessionChange)) setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return <section className={editor ? "pipeline-workspace" : undefined}>
    <h2>Мои пайплайны</h2>
    {error && <p role="alert">{error}</p>}
    {editor ? <PipelineEditor
      initial={editor.graph} catalog={editor.catalog} id={editor.id} version={editor.version}
      accountId={accountId} onSessionChange={onSessionChange} close={() => setEditor(undefined)}
      onSaved={(saved, graph) => {
        const updated = { id: saved.id, name: graph.name, latest_version: saved.version };
        setList((current) => current.some((item) => item.id === saved.id)
          ? current.map((item) => item.id === saved.id ? updated : item)
          : [...current, updated]);
        onPipelineSaved?.();
      }}
    /> : <>
      <button type="button" disabled={busy} onClick={() => void open()}>Создать пайплайн</button>
      {busy && <p role="status">Загрузка пайплайнов…</p>}
      {!busy && list.length === 0 && !error && <p>Сохранённых пайплайнов пока нет.</p>}
      <ul>{list.map((item) => <li key={item.id}>
        <button type="button" disabled={busy} onClick={() => void open(item.id)}>{item.name}</button>
        {" "}· версия {item.latest_version}
      </li>)}</ul>
    </>}
  </section>;
}

export function PipelineEditor({ initial, catalog, id, version, accountId, onSessionChange, onSaved, close }: Session & {
  initial: Pipeline; catalog: BlockCatalogItem[]; id?: string; version?: number;
  onSaved: (saved: { id: string; version: number }, graph: Pipeline) => void; close: () => void;
}) {
  const [graph, setGraph] = useState(initial);
  const [savedGraph, setSavedGraph] = useState(initial);
  const [saved, setSaved] = useState<SavedVersion | null>(id && version !== undefined ? { id, version } : null);
  const [uncertainSave, setUncertainSave] = useState<UncertainSave | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [issues, setIssues] = useState<Problem[]>([]);
  const [warnings, setWarnings] = useState<Problem[]>([]);
  const [status, setStatus] = useState("");
  const byId = new Map(catalog.map((item) => [item.id, item]));
  const readOnly = readOnlyReason(graph, byId);
  const node = graph.nodes.find((item) => item.id === selected);
  const manifest = node?.type === "block" ? byId.get(node.block) : undefined;

  function change(next: Pipeline) {
    setGraph(next);
    setError("");
    setIssues([]);
    setWarnings([]);
    setStatus("");
  }

  function accept(response: SavedVersion, persisted: Pipeline, notices: Problem[] = []) {
    setSaved(response);
    setSavedGraph(persisted);
    setWarnings(notices);
    onSaved(response, persisted);
  }

  async function save() {
    if (readOnly || pending || !graph.name.trim()) return;
    setPending(true);
    setError("");
    setIssues([]);
    setWarnings([]);
    setStatus("");
    let previous = saved;
    let sent = false;
    try {
      if (uncertainSave) {
        const candidate = uncertainSave.previous?.id ??
          (await api.pipelines(accountId)).find((item) => item.slug === uncertainSave.graph.id)?.id;
        const persisted = candidate ? await api.pipeline(accountId, candidate) : undefined;
        setUncertainSave(null);
        if (persisted && persisted.latest_version > (uncertainSave.previous?.version ?? 0)) {
          previous = { id: persisted.id, version: persisted.latest_version };
          accept(previous, persisted.graph);
          if (sameGraph(graph, persisted.graph)) {
            setStatus(`Сохранение подтверждено. Версия ${previous.version}.`);
            return;
          }
        }
      }
      sent = true;
      const response = await api.savePipeline(accountId, graph, previous?.id);
      accept(response, graph, response.warnings);
      setStatus(`Сохранено. Версия ${response.version}.`);
    } catch (failure) {
      if (sent && (!(failure instanceof ApiError) || failure.status >= 500)) {
        setUncertainSave({ graph, previous });
        setError("Ответ на сохранение потерян. При повторе редактор сначала проверит последнюю версию на сервере.");
      } else if (!sessionError(failure, onSessionChange)) setError(errorMessage(failure));
      if (failure instanceof ApiError) setIssues(failure.problems);
    } finally {
      setPending(false);
    }
  }

  return <>
    <div className="actions">
      <button type="button" disabled={pending} onClick={() => {
        if (sameGraph(graph, savedGraph) ||
          window.confirm("В пайплайне есть несохранённые изменения. Вернуться к списку без сохранения?")) close();
      }}>К списку</button>
      <button type="button" disabled={Boolean(readOnly) || pending || !graph.name.trim()}
        onClick={() => void save()}>{pending ? "Сохранение…" : "Сохранить"}</button>
      {saved && <span>Версия {saved.version}</span>}
    </div>
    {status && <p role="status">{status}</p>}
    {warnings.length > 0 && <ul aria-label="Предупреждения">{warnings.map((warning, index) =>
      <li key={index}>{warning.node && `${graph.nodes.find((item) => item.id === warning.node)?.title || warning.node}: `}{warning.message}</li>)}</ul>}
    {error && <div role="alert">
      <p>{error}</p>
      {issues.some((issue) => !graph.nodes.some((item) => item.id === issue.node)) &&
        <ul>{issues.filter((issue) => !graph.nodes.some((item) => item.id === issue.node)).map((issue, index) =>
          <li key={index}>{issue.message}</li>)}</ul>}
    </div>}
    {readOnly && <p role="status">{readOnly}</p>}
    <fieldset className="pipeline-editor" disabled={pending || Boolean(readOnly)}>
      <label>Название пайплайна<input value={graph.name}
        onChange={(event) => change({ ...graph, name: event.target.value })} /></label>
      <PipelineParameters graph={graph} change={change} />
      <div className="pipeline-layout">
        <aside className="pipeline-catalog" aria-label="Каталог блоков">
          <h3>Блоки</h3>
          {Object.entries(categories).map(([category, title]) => {
            const blocks = catalog.filter((item) => item.category === category);
            if (!blocks.length) return null;
            return <div key={category}>
              <h4>{title}</h4>
              {blocks.map((item) => <button key={item.id} type="button" title={item.description} onClick={() => {
                const block = makeBlock(graph, item);
                change({ ...graph, nodes: [...graph.nodes, block] });
                setSelected(block.id);
              }}>{item.name}</button>)}
            </div>;
          })}
        </aside>
        <div>
          <PipelineCanvas graph={graph} catalog={byId} selected={selected} select={setSelected} change={change}
            issues={issues} readOnly={pending || Boolean(readOnly)} />
        </div>
        <aside className="pipeline-settings" aria-label="Настройки узла">
          <h3>Настройки узла</h3>
          {node?.type === "block" && manifest ? <>
            <BlockSettings graph={graph} node={node} manifest={manifest} change={(next) => change(updateNode(graph, next))} />
            <button type="button" onClick={() => { change(removeNode(graph, node.id)); setSelected(null); }}>Убрать блок</button>
          </> : node?.type === "trigger"
            ? <p>Запуск: {node.launches.map((launch) => launch.type === "student" ? "ученик открыл урок" : launch.type).join(", ")}.</p>
            : <p>Выберите блок на схеме.</p>}
        </aside>
      </div>
    </fieldset>
  </>;
}
