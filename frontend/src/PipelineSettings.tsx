import { useState } from "react";
import type { BlockCatalogItem, Pipeline } from "./api";
import { fitsParam, identifier, paramName, usesParam } from "./pipelineGraph";
import type { BlockNode, Param } from "./pipelineGraph";

type Schema = Record<string, unknown>;
const types: Record<Param["type"], string> = {
  string: "Текст", integer: "Целое число", number: "Число", boolean: "Да / нет",
};

function object(value: unknown): Schema {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Schema : {};
}

function Field({ label, schema, value, change }: {
  label: string; schema: Schema; value: unknown; change: (value: unknown) => void;
}) {
  const shown = value ?? schema.default;
  const choices = object(schema.items).enum;
  if (schema.type === "array" && Array.isArray(choices) && choices.every((choice) => typeof choice === "string")) {
    const selected: unknown[] = Array.isArray(shown) ? shown : [];
    return <fieldset><legend>{label}</legend>{choices.map((choice: string) => (
      <label key={choice} className="pipeline-check">
        <input type="checkbox" checked={selected.includes(choice)} onChange={(event) =>
          change(event.target.checked ? [...selected, choice] : selected.filter((item) => item !== choice))} />
        {choice}
      </label>
    ))}</fieldset>;
  }
  if (schema.type === "boolean") {
    return <label>{label}<select value={typeof value === "boolean" ? String(value) : ""} onChange={(event) =>
      change(event.target.value === "" ? undefined : event.target.value === "true")}>
      <option value="">По умолчанию{typeof shown === "boolean" ? (shown ? " (да)" : " (нет)") : ""}</option>
      <option value="true">Да</option><option value="false">Нет</option>
    </select></label>;
  }
  if (schema.type === "integer" || schema.type === "number") {
    return <label>{label}<input type="number" step={schema.type === "integer" ? 1 : "any"}
      min={typeof schema.minimum === "number" ? schema.minimum : undefined}
      max={typeof schema.maximum === "number" ? schema.maximum : undefined}
      placeholder={typeof schema.default === "number" ? String(schema.default) : undefined}
      value={typeof value === "number" ? value : ""}
      onChange={(event) => change(event.target.value === "" ? undefined : event.target.valueAsNumber)} /></label>;
  }
  if (schema.type === "string") {
    const isSet = typeof value === "string";
    return <div className="pipeline-setting">
      <label>{label}<input value={isSet ? value : ""}
        placeholder={!isSet && typeof schema.default === "string" ? schema.default : undefined}
        onChange={(event) => change(event.target.value)} /></label>
      <button type="button" aria-label={`${label} · ${isSet ? "сбросить значение" : "задать пустую строку"}`}
        onClick={() => change(isSet ? undefined : "")}>
        {isSet ? "Сбросить значение" : "Задать пустую строку"}
      </button>
    </div>;
  }
  return <p>{label} · для этого поля нет формы</p>;
}

function Value({ label, schema, value, params, change }: {
  label: string; schema: Schema; value: unknown; params: Param[]; change: (value: unknown) => void;
}) {
  const name = paramName(value);
  const matches = params.filter((param) => fitsParam(param, schema.type) || param.name === name);
  return <div className="pipeline-setting">
    {(matches.length > 0 || name) && <label>{label} · источник
      <select value={name ?? ""} onChange={(event) => change(event.target.value ? { $param: event.target.value } : undefined)}>
        <option value="">Значение в настройках</option>
        {matches.map((param) => <option key={param.name} value={param.name}>Параметр: {param.title || param.name}</option>)}
        {name && !matches.some((param) => param.name === name) && <option value={name}>{name}</option>}
      </select>
    </label>}
    {!name && <Field label={label} schema={schema} value={value} change={change} />}
  </div>;
}

export function PipelineParameters({ graph, change }: { graph: Pipeline; change: (graph: Pipeline) => void }) {
  const [name, setName] = useState("");
  function edit(param: Param) {
    change({ ...graph, params: graph.params.map((item) => item.name === param.name ? param : item) });
  }
  return <details className="pipeline-parameters">
    <summary>Параметры пайплайна</summary>
    {graph.params.map((param) => {
      const used = usesParam(graph, param.name);
      return <fieldset key={param.name}>
        <legend>{param.name}</legend>
        <label>Название параметра<input value={param.title} onChange={(event) => edit({ ...param, title: event.target.value })} /></label>
        <label>Тип<select value={param.type} disabled={used}
          onChange={(event) => edit({ ...param, type: event.target.value as Param["type"], default: null })}>
          {Object.entries(types).map(([type, title]) => <option key={type} value={type}>{title}</option>)}
        </select></label>
        <Field label="По умолчанию" schema={{ type: param.type }} value={param.default}
          change={(value) => edit({ ...param, default: value ?? null })} />
        <button type="button" disabled={used} onClick={() => change({ ...graph, params: graph.params.filter((item) => item !== param) })}>
          Убрать параметр
        </button>
        {used && <small>Параметр используется в настройках блока.</small>}
      </fieldset>;
    })}
    <label>Код нового параметра<input value={name} onChange={(event) => setName(event.target.value)} placeholder="например, topic" /></label>
    <button type="button" disabled={!identifier.test(name) || graph.params.some((param) => param.name === name)} onClick={() => {
      change({ ...graph, params: [...graph.params, { name, title: name, type: "string" }] });
      setName("");
    }}>Добавить параметр</button>
    <small>Код начинается с латинской буквы. Допустимы строчные буквы, цифры и подчёркивание.</small>
  </details>;
}

export function BlockSettings({ graph, node, manifest, change }: {
  graph: Pipeline; node: BlockNode; manifest: BlockCatalogItem; change: (node: BlockNode) => void;
}) {
  const limit = node.limit;
  return <>
    <label>Название узла<input value={node.title} onChange={(event) => change({ ...node, title: event.target.value })} /></label>
    <p>{manifest.description}</p>
    {manifest.side_effects && <p>Этот блок может изменить данные во внешней системе.</p>}
    {Object.entries(object(manifest.config.properties)).map(([key, raw]) => {
      const schema = object(raw);
      const label = typeof schema.title === "string" ? schema.title : key;
      return <Value key={key} label={label} schema={schema} value={node.config[key]} params={graph.params} change={(value) => {
        const config = { ...node.config };
        if (value === undefined) delete config[key];
        else config[key] = value;
        change({ ...node, config });
      }} />;
    })}
    <label className="pipeline-check"><input type="checkbox" checked={Boolean(limit)} onChange={(event) =>
      change({ ...node, limit: event.target.checked ? { max: 1 } : null })} />Ограничить число проходов</label>
    {limit && <>
      <Value label="Число проходов" schema={{ type: "integer", minimum: 1 }} value={limit.max}
        params={graph.params} change={(value) => {
          const name = paramName(value);
          change({ ...node, limit: { ...limit, max: typeof value === "number" ? value : name ? { $param: name } : 1 } });
        }} />
      <label>Обнулить счётчик при выполнении<select value={limit.reset_on ?? ""} onChange={(event) =>
        change({ ...node, limit: { ...limit, reset_on: event.target.value || null } })}>
        <option value="">Без сброса</option>
        {graph.nodes.map((item) => <option key={item.id} value={item.id}>{item.title || item.id}</option>)}
      </select></label>
      <label>Куда перейти по достижении предела<select value={limit.otherwise ?? ""} onChange={(event) =>
        change({ ...node, limit: { ...limit, otherwise: event.target.value || null } })}>
        <option value="">Закончить ветку</option>
        {graph.nodes.filter((item) => item.type !== "trigger").map((item) =>
          <option key={item.id} value={item.id}>{item.title || item.id}</option>)}
      </select></label>
    </>}
  </>;
}
