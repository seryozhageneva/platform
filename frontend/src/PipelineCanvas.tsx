import { useEffect, useState } from "react";
import { Background, BaseEdge, Controls, Handle, MarkerType, Position, ReactFlow, getBezierPath, useUpdateNodeInternals } from "@xyflow/react";
import type { Edge, EdgeProps, Node, NodeProps, XYPosition } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { BlockCatalogItem, Pipeline, Problem } from "./api";
import { connect, graphLinks, outputPorts } from "./pipelineGraph";

type Point = { id: string; label: string; type: "source" | "target" };
type CanvasNode = Node<{ title: string; points: Point[]; issues: Problem[] }, "lesson">;
type CanvasEdge = Edge<{ loop: number }, "pipeline">;

function LessonNode({ id, data, selected, isConnectable }: NodeProps<CanvasNode>) {
  const updateInternals = useUpdateNodeInternals();
  const handleLayout = data.points.map((point) => point.id).join("|");
  useEffect(() => { updateInternals(id); }, [handleLayout, id, updateInternals]);
  return <div className={`pipeline-node${selected ? " pipeline-node-selected" : ""}`}>
    <strong>{data.title}</strong>
    {data.issues.length > 0 && <ul className="pipeline-node-issues">{data.issues.map((issue, index) =>
      <li key={index}>{issue.message}</li>)}</ul>}
    {data.points.map((point) => <div key={point.id} className={`pipeline-port ${point.type}`}>
      {point.label}
      <Handle id={point.id} type={point.type} position={point.type === "target" ? Position.Left : Position.Right}
        className={point.id.startsWith("in:") || point.id.startsWith("out:") ? "pipeline-data-port" : undefined}
        isConnectable={isConnectable && point.id !== "limit"} aria-label={point.label} />
    </div>)}
  </div>;
}

function PipelineEdge(props: EdgeProps<CanvasEdge>) {
  const { id, source, target, sourceX, sourceY, targetX, targetY, label, markerEnd, style } = props;
  if (source === target) {
    const offset = 32 + (props.data?.loop ?? 0) * 14;
    const y = Math.min(sourceY, targetY) - 90 - offset;
    const path = `M ${sourceX} ${sourceY} C ${sourceX + offset} ${sourceY}, ${sourceX + offset} ${y}, ${sourceX} ${y}
      L ${targetX} ${y} C ${targetX - offset} ${y}, ${targetX - offset} ${targetY}, ${targetX} ${targetY}`;
    return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} label={label}
      labelX={(sourceX + targetX) / 2} labelY={y} />;
  }
  const [path, labelX, labelY] = getBezierPath(props);
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} label={label} labelX={labelX} labelY={labelY} />;
}

const nodeTypes = { lesson: LessonNode };
const edgeTypes = { pipeline: PipelineEdge };

export function PipelineCanvas({ graph, catalog, selected, select, change, issues, readOnly }: {
  graph: Pipeline; catalog: Map<string, BlockCatalogItem>; selected: string | null;
  select: (id: string | null) => void; change: (graph: Pipeline) => void; issues: Problem[]; readOnly: boolean;
}) {
  const [positions, setPositions] = useState<Record<string, XYPosition>>({});
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const links = graphLinks(graph);
  const nodes: CanvasNode[] = graph.nodes.map((node, index) => {
    const manifest = node.type === "block" ? catalog.get(node.block) : undefined;
    const points: Point[] = [];
    if (node.type !== "trigger") points.push({ id: "step", label: "Выполнить", type: "target" });
    for (const input of manifest?.inputs ?? []) {
      points.push({ id: `in:${input.name}`, label: `${input.title}${input.required ? " *" : ""}`, type: "target" });
    }
    for (const output of outputPorts(node, catalog)) {
      points.push({ id: `out:${output.name}`, label: output.title, type: "source" });
    }
    const outcomes = new Set([...(manifest?.outcomes ?? []),
      ...graph.transitions.flatMap((edge) => edge.from === node.id && edge.when ? [edge.when] : [])]);
    for (const outcome of outcomes) points.push({ id: `step:${outcome}`, label: outcome, type: "source" });
    points.push({ id: "step:", label: node.type === "trigger" ? "Начать" : "Иначе / дальше", type: "source" });
    if (node.type !== "trigger" && node.limit?.otherwise) {
      points.push({ id: "limit", label: "Предел достигнут", type: "source" });
    }
    for (const link of links) {
      if (link.source === node.id && !points.some((point) => point.id === link.sourceHandle)) {
        points.push({ id: link.sourceHandle, label: link.sourceHandle.split(":").at(-1) ?? "", type: "source" });
      }
      if (link.target === node.id && !points.some((point) => point.id === link.targetHandle)) {
        points.push({ id: link.targetHandle, label: link.targetHandle.split(":").at(-1) ?? "", type: "target" });
      }
    }
    return {
      id: node.id, type: "lesson", selected: selected === node.id, deletable: false,
      position: positions[node.id] ?? { x: (index % 3) * 295, y: Math.floor(index / 3) * 430 },
      data: {
        title: node.title || manifest?.name || node.id, points,
        issues: issues.filter((item) => item.node === node.id),
      },
    };
  });
  const edges: CanvasEdge[] = links.map(({ id, source, target, sourceHandle, targetHandle, label }, index) => {
    const dataLink = id.startsWith("data:");
    const color = dataLink ? "#2563eb" : "#334155";
    const loop = source === target ? links.slice(0, index).filter((item) => item.source === source && item.target === target).length : 0;
    return {
      id, source, target, sourceHandle, targetHandle, label,
      type: "pipeline", selected: selectedEdge === id, deletable: false, data: { loop },
      style: { stroke: color, strokeWidth: selectedEdge === id ? 3 : 1.5, strokeDasharray: dataLink ? "5 4" : undefined },
      markerEnd: { type: MarkerType.ArrowClosed, color },
    };
  });
  const removable = links.find((link) => link.id === selectedEdge)?.remove;
  return <>
    <p className="pipeline-legend">Сплошная стрелка — что выполнить дальше. Синяя пунктирная — откуда взять данные. * Обязательный вход.</p>
    <div className="pipeline-canvas">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        minZoom={0.25} fitView={graph.nodes.length > 1} defaultViewport={{ x: 35, y: 45, zoom: 0.7 }}
        nodesConnectable={!readOnly} deleteKeyCode={null}
        onNodesChange={(changes) => {
          for (const item of changes) {
            if (item.type === "position" && item.position) {
              const position = item.position;
              setPositions((current) => ({ ...current, [item.id]: position }));
            }
          }
        }}
        onNodeClick={(_, node) => { setSelectedEdge(null); select(node.id); }}
        onEdgeClick={(_, edge) => { select(null); setSelectedEdge(edge.id); }}
        onPaneClick={() => { select(null); setSelectedEdge(null); }}
        isValidConnection={(connection) => connect(graph, catalog, connection) !== null}
        onConnect={(connection) => {
          const next = connect(graph, catalog, connection);
          if (next && !readOnly) change(next);
        }}>
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
    {removable && !readOnly && <button type="button" onClick={() => {
      change(removable(graph));
      setSelectedEdge(null);
    }}>Убрать связь</button>}
  </>;
}
