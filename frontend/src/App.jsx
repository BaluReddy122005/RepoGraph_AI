import React, { useState, useEffect, useRef, useCallback } from 'react';
import ForceGraph3D from '3d-force-graph';
import {
  MessageSquare, GitGraph, Database, Search, Terminal,
  CheckCircle, X, Plus, ArrowRight, ArrowLeft,
} from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('ask');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [headerStats, setHeaderStats] = useState({ repo: 'pallets/flask', commit: '36e4a82', nodes: 998 });

  // Directory state
  const [dirSearch, setDirSearch] = useState('');
  const [dirType, setDirType] = useState('');
  const [dirNodes, setDirNodes] = useState([]);

  // Vis network
  const visContainerRef = useRef(null);
  const networkRef = useRef(null);
  const visDataRef = useRef(null);

  // Graph Explorer — Inspector panel state
  const [selectedNode, setSelectedNode] = useState(null);
  const [nodeDetail, setNodeDetail] = useState(null);
  const [inspectorLoading, setInspectorLoading] = useState(false);

  // Graph Explorer — Add Node modal state
  const [showAddNode, setShowAddNode] = useState(false);
  const [addNodeForm, setAddNodeForm] = useState({
    type: 'Function', name: '', file: '', line_start: 1,
    line_end: '', qualified_name: '', signature: '', docstring: '',
  });
  const [addNodeStatus, setAddNodeStatus] = useState(null);

  // Graph Explorer — Search/highlight state
  const [graphSearch, setGraphSearch] = useState('');

  useEffect(() => { fetchStats(); }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/graph/stats');
      const data = await res.json();
      setHeaderStats({
        repo: data.repo || 'pallets/flask',
        commit: data.pinned_commit ? data.pinned_commit.substring(0, 7) : '36e4a82',
        nodes: data.metadata?.total_nodes || 998,
      });
    } catch (e) { console.warn('Failed to fetch stats:', e); }
  };

  const handleAsk = async (qText) => {
    const searchQuery = qText || query;
    if (!searchQuery.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: searchQuery }),
      });
      setResult(await res.json());
    } catch (e) { alert('Error: ' + e.message); }
    finally { setLoading(false); }
  };

  // ── Graph Explorer: Init 3D network ──
  useEffect(() => {
    if (activeTab === 'graph' && visContainerRef.current && !networkRef.current) {
      initNetwork();
    }
    return () => {
      // Cleanup on unmount
      if (activeTab !== 'graph' && networkRef.current) {
        // Keep alive across tab switches — only cleanup ref on actual unmount
      }
    };
  }, [activeTab]);

  const initNetwork = async () => {
    try {
      const res = await fetch('/api/graph/vis');
      const data = await res.json();

      visDataRef.current = { nodesRaw: data.nodes, edgesRaw: data.edges };

      const graphData = {
        nodes: data.nodes.map((n) => ({
          id: n.id,
          name: n.label,
          group: n.group,
          file: n.file,
          val: n.group === 'File' ? 8 : n.group === 'Class' ? 5 : 2,
        })),
        links: data.edges.map((e) => ({
          source: e.from,
          target: e.to,
          edgeType: e.type,
        })),
      };

      const container = visContainerRef.current;
      const graph = ForceGraph3D()(container)
        .graphData(graphData)
        .backgroundColor('#0a0a0a')
        .width(container.clientWidth)
        .height(container.clientHeight)
        // Node appearance
        .nodeColor((node) =>
          node.group === 'File' ? '#ffffff'
          : node.group === 'Class' ? '#b0b0b0'
          : '#686868'
        )
        .nodeOpacity(0.95)
        .nodeResolution(16)
        .nodeLabel((node) => `[${node.group}] ${node.name}\n${node.file || ''}`)
        // Link appearance
        .linkColor((link) =>
          link.edgeType === 'CONTAINS' ? '#444444'
          : link.edgeType === 'CALLS' ? '#555555'
          : '#3a3a3a'
        )
        .linkWidth(0.4)
        .linkOpacity(0.35)
        .linkDirectionalArrowLength(3)
        .linkDirectionalArrowRelPos(1)
        .linkDirectionalArrowColor(() => '#888888')
        // Interaction
        .onNodeClick((node) => {
          fetchNodeDetail(node.id);
          // Camera fly to clicked node
          const distance = 120;
          const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z);
          graph.cameraPosition(
            { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
            node,
            1500
          );
        })
        .onBackgroundClick(() => {
          setSelectedNode(null);
          setNodeDetail(null);
        });

      // Handle window resize
      const handleResize = () => {
        if (container) {
          graph.width(container.clientWidth).height(container.clientHeight);
        }
      };
      window.addEventListener('resize', handleResize);

      networkRef.current = graph;
    } catch (e) {
      console.warn('3D graph error:', e);
    }
  };

  // ── Graph Explorer: Fetch node detail ──
  const fetchNodeDetail = async (nodeId) => {
    setSelectedNode(nodeId);
    setInspectorLoading(true);
    setNodeDetail(null);
    try {
      const res = await fetch(`/api/graph/node?id=${encodeURIComponent(nodeId)}`);
      if (res.ok) {
        setNodeDetail(await res.json());
      }
    } catch (e) { console.warn('Node detail error:', e); }
    finally { setInspectorLoading(false); }
  };

  // ── Graph Explorer: Search & highlight ──
  const handleGraphSearch = () => {
    if (!networkRef.current || !visDataRef.current) return;
    const q = graphSearch.toLowerCase().trim();
    if (!q) return;

    const graphData = networkRef.current.graphData();
    const match = graphData.nodes.find((n) => {
      const name = (n.name || '').toLowerCase();
      const file = (n.file || '').toLowerCase();
      return name.includes(q) || file.includes(q);
    });

    if (match) {
      // Fly camera to the matching node
      const distance = 120;
      const distRatio = 1 + distance / Math.hypot(match.x, match.y, match.z);
      networkRef.current.cameraPosition(
        { x: match.x * distRatio, y: match.y * distRatio, z: match.z * distRatio },
        match,
        1500
      );
      // Also open the inspector
      fetchNodeDetail(match.id);
    }
  };

  // ── Graph Explorer: Add node ──
  const handleAddNode = async () => {
    setAddNodeStatus(null);
    try {
      const body = {
        type: addNodeForm.type,
        name: addNodeForm.name,
        file: addNodeForm.file,
        line_start: parseInt(addNodeForm.line_start) || 1,
        line_end: addNodeForm.line_end ? parseInt(addNodeForm.line_end) : null,
        qualified_name: addNodeForm.qualified_name || null,
        signature: addNodeForm.signature || null,
        docstring: addNodeForm.docstring || null,
      };
      const res = await fetch('/api/graph/nodes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (res.ok) {
        setAddNodeStatus({ ok: true, msg: data.message });
        // Add to 3D force graph
        if (networkRef.current) {
          const n = data.node;
          const gd = networkRef.current.graphData();
          gd.nodes.push({
            id: n.id, name: n.name, group: n.type, file: n.file,
            val: n.type === 'File' ? 8 : n.type === 'Class' ? 5 : 2,
          });
          networkRef.current.graphData(gd);
        }
        fetchStats();
        // Reset form
        setAddNodeForm({ type: 'Function', name: '', file: '', line_start: 1, line_end: '', qualified_name: '', signature: '', docstring: '' });
      } else {
        setAddNodeStatus({ ok: false, msg: data.detail || 'Failed to add node.' });
      }
    } catch (e) {
      setAddNodeStatus({ ok: false, msg: e.message });
    }
  };

  // ── Directory ──
  useEffect(() => {
    if (activeTab === 'directory') fetchDirectory();
  }, [activeTab, dirSearch, dirType]);

  const fetchDirectory = async () => {
    try {
      const url = `/api/graph/nodes?limit=100${dirSearch ? `&q=${encodeURIComponent(dirSearch)}` : ''}${dirType ? `&type=${dirType}` : ''}`;
      const res = await fetch(url);
      const data = await res.json();
      setDirNodes(data.nodes || []);
    } catch (e) { console.warn('Directory error:', e); }
  };

  // ── Citation formatter ──
  const formatAnswer = (text) => {
    if (!text) return '';
    const parts = text.split(/(\[[^\]]+:[^\]]+:L\d+\])/g);
    return parts.map((part, i) => {
      if (part.match(/^\[[^\]]+:[^\]]+:L\d+\]$/)) {
        return (
          <span key={i} style={{
            display: 'inline-flex', alignItems: 'center',
            background: '#1f1f1f', border: '1px solid #404040',
            color: '#fff', fontFamily: 'var(--font-mono)', fontSize: '0.78rem',
            padding: '2px 6px', borderRadius: '4px', margin: '0 4px',
          }}>
            📍 {part.slice(1, -1)}
          </span>
        );
      }
      return part;
    });
  };

  // ── Shared styles ──
  const panelStyle = {
    background: 'var(--panel-bg)', border: '1px solid var(--panel-border)',
    borderRadius: '12px', padding: '1.5rem',
  };
  const inputStyle = {
    background: '#0a0a0a', border: '1px solid var(--panel-border)',
    borderRadius: '8px', padding: '0.75rem 1rem', fontSize: '0.9rem',
    color: '#fff', outline: 'none', width: '100%',
  };
  const btnWhite = {
    background: '#fff', color: '#000', border: 'none', borderRadius: '8px',
    padding: '0.55rem 1.3rem', fontWeight: 700, cursor: 'pointer', fontSize: '0.85rem',
  };
  const btnOutline = {
    background: 'transparent', color: '#fff', border: '1px solid var(--panel-border)',
    borderRadius: '8px', padding: '0.5rem 1rem', fontWeight: 500, cursor: 'pointer', fontSize: '0.82rem',
  };
  const labelStyle = {
    fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block',
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-black)' }}>

      {/* ═══════════════════ HEADER ═══════════════════ */}
      <header style={{
        borderBottom: '1px solid var(--panel-border)', background: '#0a0a0a',
        padding: '0.9rem 2rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        position: 'sticky', top: 0, zIndex: 100,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.8rem' }}>
          <div style={{
            width: '32px', height: '32px', borderRadius: '6px', background: '#fff', color: '#000',
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.9rem',
          }}>RG</div>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 700, letterSpacing: '-0.3px' }}>RepoGraph AI</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Codebase Knowledge Assistant</div>
          </div>
        </div>

        <div style={{ display: 'flex', background: '#121212', padding: '3px', borderRadius: '8px', border: '1px solid var(--panel-border)' }}>
          {[['ask', MessageSquare, 'Ask AI'], ['graph', GitGraph, 'Graph Explorer'], ['directory', Database, 'Schema & Nodes']].map(([key, Icon, label]) => (
            <button key={key} onClick={() => setActiveTab(key)} style={{
              background: activeTab === key ? '#fff' : 'transparent',
              color: activeTab === key ? '#000' : 'var(--text-secondary)',
              border: 'none', padding: '0.45rem 1.1rem', fontSize: '0.82rem', fontWeight: 600,
              borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem',
              transition: 'all 0.15s',
            }}>
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', gap: '0.6rem' }}>
          {[['Repo', headerStats.repo], ['Commit', headerStats.commit], ['Nodes', headerStats.nodes]].map(([k, v]) => (
            <div key={k} style={{
              background: '#121212', border: '1px solid var(--panel-border)',
              padding: '0.3rem 0.7rem', borderRadius: '6px', fontSize: '0.75rem',
              color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)',
            }}>
              {k}: <strong style={{ color: '#fff' }}>{v}</strong>
            </div>
          ))}
        </div>
      </header>

      {/* ═══════════════════ MAIN ═══════════════════ */}
      <main style={{ flex: 1, padding: '2rem', maxWidth: '1400px', margin: '0 auto', width: '100%' }}>

        {/* ─── TAB 1: ASK AI ─── */}
        {activeTab === 'ask' && (
          <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            <div style={panelStyle}>
              <div style={{ display: 'flex', gap: '0.75rem' }}>
                <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
                  placeholder="Ask any natural-language question about the codebase..."
                  style={{ ...inputStyle, flex: 1 }} />
                <button onClick={() => handleAsk()} style={btnWhite}>Ask RepoGraph</button>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '1rem' }}>
                {[
                  'Which functions are registered as HTTP routes?',
                  'Explain how application context and request context work.',
                  'Which functions handle request dispatching?',
                  'Which classes implement blueprint interfaces?',
                  'Which functions publish Kafka events?',
                ].map((p, i) => (
                  <button key={i} onClick={() => { setQuery(p); handleAsk(p); }}
                    style={{ ...btnOutline, borderRadius: '20px', padding: '0.35rem 0.8rem', fontSize: '0.78rem', color: 'var(--text-secondary)' }}
                    onMouseEnter={(e) => { e.target.style.borderColor = '#fff'; e.target.style.color = '#fff'; }}
                    onMouseLeave={(e) => { e.target.style.borderColor = 'var(--panel-border)'; e.target.style.color = 'var(--text-secondary)'; }}>
                    {p}
                  </button>
                ))}
              </div>
            </div>

            {loading && (
              <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--text-secondary)' }}>
                <div style={{ width: '28px', height: '28px', border: '3px solid #262626', borderTop: '3px solid #fff', borderRadius: '50%', margin: '0 auto 1rem', animation: 'spin 0.8s linear infinite' }}></div>
                <div style={{ fontSize: '0.88rem', fontFamily: 'var(--font-mono)' }}>Traversing knowledge graph…</div>
              </div>
            )}

            {result && !loading && (
              <div className="animate-fade-in" style={{ display: 'grid', gridTemplateColumns: '2.2fr 1fr', gap: '1.5rem' }}>
                <div style={panelStyle}>
                  <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <CheckCircle size={16} /> Grounded Answer & Citations
                  </h3>
                  <div style={{ fontSize: '0.92rem', lineHeight: 1.65, color: '#e5e5e5', whiteSpace: 'pre-wrap', background: '#0a0a0a', padding: '1.25rem', borderRadius: '8px', border: '1px solid var(--panel-border)' }}>
                    {formatAnswer(result.answer)}
                  </div>
                  <h4 style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '1.5rem', marginBottom: '0.6rem' }}>
                    Sources ({result.sources?.length || 0})
                  </h4>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                    {result.sources?.length > 0 ? result.sources.map((s, i) => (
                      <span key={i} style={{ background: '#1a1a1a', border: '1px solid var(--panel-border)', color: '#fff', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', padding: '3px 8px', borderRadius: '4px' }}>
                        {s.file}:{s.symbol}:L{s.line}
                      </span>
                    )) : <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>No sources (out-of-scope)</span>}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                  <div style={{ ...panelStyle, textAlign: 'center' }}>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Retrieval Confidence</div>
                    <div style={{ fontSize: '2.2rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: result.confidence > 0.7 ? '#fff' : result.confidence > 0.3 ? '#a3a3a3' : '#737373', margin: '0.5rem 0' }}>
                      {Math.round(result.confidence * 100)}%
                    </div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>{result.confidence_justification}</div>
                  </div>
                  <div style={{ ...panelStyle, flex: 1 }}>
                    <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <Terminal size={14} /> Reasoning Trace
                    </div>
                    <div style={{ fontSize: '0.76rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', maxHeight: '320px', overflowY: 'auto' }}>
                      {result.reasoning_trace?.map((step, i) => (
                        <div key={i} style={{ padding: '0.35rem 0', borderBottom: '1px solid #1a1a1a', lineHeight: 1.4 }}>{step}</div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ─── TAB 2: GRAPH EXPLORER ─── */}
        {activeTab === 'graph' && (
          <div className="animate-fade-in" style={{ display: 'flex', gap: '1.5rem', height: 'calc(100vh - 140px)' }}>

            {/* Left: Graph canvas */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {/* Toolbar */}
              <div style={{ ...panelStyle, padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1 }}>
                  <Search size={14} style={{ color: 'var(--text-muted)' }} />
                  <input type="text" value={graphSearch} onChange={(e) => setGraphSearch(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleGraphSearch()}
                    placeholder="Search nodes by name or file…"
                    style={{ ...inputStyle, padding: '0.5rem 0.75rem', fontSize: '0.85rem', border: 'none', background: 'transparent' }} />
                  <button onClick={handleGraphSearch} style={{ ...btnOutline, padding: '0.35rem 0.8rem', fontSize: '0.78rem' }}>Find</button>
                </div>
                <button onClick={() => setShowAddNode(true)} style={{ ...btnWhite, padding: '0.4rem 0.9rem', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <Plus size={14} /> Add Node
                </button>
                <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  <span>⚪ File</span><span>🔘 Class</span><span>⚫ Function</span>
                </div>
              </div>

              {/* Vis canvas */}
              <div ref={visContainerRef} style={{
                flex: 1, background: '#0a0a0a', borderRadius: '12px',
                border: '1px solid var(--panel-border)', minHeight: '500px',
              }}></div>

              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                Click any node to inspect its properties • Scroll to zoom • Drag to pan
              </div>
            </div>

            {/* Right: Inspector Panel */}
            <div style={{
              width: nodeDetail ? '380px' : '0px', overflow: 'hidden',
              transition: 'width 0.25s ease', flexShrink: 0,
            }}>
              {nodeDetail && (
                <div style={{ ...panelStyle, height: '100%', overflowY: 'auto', width: '380px' }}>
                  {/* Close button */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700 }}>Node Inspector</h3>
                    <button onClick={() => { setSelectedNode(null); setNodeDetail(null); }}
                      style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                      <X size={18} />
                    </button>
                  </div>

                  {inspectorLoading ? (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading…</div>
                  ) : (
                    <>
                      {/* Node type badge */}
                      <div style={{ marginBottom: '1.25rem' }}>
                        <span style={{
                          padding: '3px 10px', borderRadius: '4px', fontSize: '0.72rem', fontWeight: 700,
                          background: nodeDetail.node.type === 'File' ? '#fff' : nodeDetail.node.type === 'Class' ? '#a3a3a3' : '#333',
                          color: nodeDetail.node.type === 'Function' ? '#fff' : '#000',
                        }}>
                          {nodeDetail.node.type}
                        </span>
                      </div>

                      {/* Properties table */}
                      {[
                        ['Name', nodeDetail.node.name],
                        ['Qualified Name', nodeDetail.node.qualified_name],
                        ['File', nodeDetail.node.file],
                        ['Lines', `${nodeDetail.node.line_start || '?'}${nodeDetail.node.line_end ? ' – ' + nodeDetail.node.line_end : ''}`],
                        ['Signature', nodeDetail.node.signature],
                        ['Route', nodeDetail.node.is_route ? `✓  ${(nodeDetail.node.route_decorators || []).join(', ')}` : null],
                        ['Config', nodeDetail.node.is_config ? '✓' : null],
                        ['Bases', nodeDetail.node.bases?.length > 0 ? nodeDetail.node.bases.join(', ') : null],
                      ].filter(([, v]) => v).map(([label, value]) => (
                        <div key={label} style={{ display: 'flex', borderBottom: '1px solid #1a1a1a', padding: '0.5rem 0' }}>
                          <div style={{ width: '110px', fontSize: '0.78rem', color: 'var(--text-muted)', flexShrink: 0 }}>{label}</div>
                          <div style={{ fontSize: '0.82rem', fontFamily: label === 'Signature' ? 'var(--font-mono)' : 'inherit', color: '#e5e5e5', wordBreak: 'break-all' }}>{value}</div>
                        </div>
                      ))}

                      {/* Docstring */}
                      {nodeDetail.node.docstring && (
                        <div style={{ marginTop: '1rem' }}>
                          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.35rem' }}>Docstring</div>
                          <div style={{
                            background: '#0a0a0a', border: '1px solid var(--panel-border)', borderRadius: '6px',
                            padding: '0.75rem', fontSize: '0.8rem', fontFamily: 'var(--font-mono)',
                            color: '#d4d4d4', lineHeight: 1.5, maxHeight: '150px', overflowY: 'auto', whiteSpace: 'pre-wrap',
                          }}>
                            {nodeDetail.node.docstring}
                          </div>
                        </div>
                      )}

                      {/* Connected edges */}
                      <div style={{ marginTop: '1.25rem' }}>
                        <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                          Connected Edges ({nodeDetail.edges?.length || 0})
                        </div>
                        <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
                          {nodeDetail.edges?.map((e, i) => {
                            const isSource = e.source === selectedNode;
                            const otherId = isSource ? e.target : e.source;
                            const neighbor = nodeDetail.neighbors?.find((nb) => nb.id === otherId);
                            return (
                              <div key={i} onClick={() => fetchNodeDetail(otherId)}
                                style={{
                                  display: 'flex', alignItems: 'center', gap: '0.5rem',
                                  padding: '0.4rem 0.5rem', borderRadius: '6px', cursor: 'pointer',
                                  fontSize: '0.78rem', color: '#d4d4d4', transition: 'background 0.15s',
                                }}
                                onMouseEnter={(e) => e.currentTarget.style.background = '#1a1a1a'}
                                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', fontSize: '0.72rem', minWidth: '70px' }}>
                                  {e.type}
                                </span>
                                {isSource ? <ArrowRight size={12} style={{ color: 'var(--text-muted)' }} /> : <ArrowLeft size={12} style={{ color: 'var(--text-muted)' }} />}
                                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.76rem' }}>
                                  {neighbor?.qualified_name || neighbor?.name || otherId}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ─── ADD NODE MODAL ─── */}
        {showAddNode && (
          <div style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 200,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }} onClick={(e) => { if (e.target === e.currentTarget) setShowAddNode(false); }}>
            <div className="animate-fade-in" style={{ ...panelStyle, width: '480px', maxHeight: '90vh', overflowY: 'auto' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
                <h3 style={{ fontSize: '1rem', fontWeight: 700 }}>Add New Node</h3>
                <button onClick={() => setShowAddNode(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                  <X size={18} />
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div>
                  <label style={labelStyle}>Node Type *</label>
                  <select value={addNodeForm.type} onChange={(e) => setAddNodeForm({ ...addNodeForm, type: e.target.value })}
                    style={{ ...inputStyle, cursor: 'pointer' }}>
                    <option value="Function">Function</option>
                    <option value="Class">Class</option>
                    <option value="File">File</option>
                  </select>
                </div>
                <div>
                  <label style={labelStyle}>Name *</label>
                  <input type="text" value={addNodeForm.name} onChange={(e) => setAddNodeForm({ ...addNodeForm, name: e.target.value })}
                    placeholder="e.g. my_function" style={inputStyle} />
                </div>
                <div>
                  <label style={labelStyle}>File Path *</label>
                  <input type="text" value={addNodeForm.file} onChange={(e) => setAddNodeForm({ ...addNodeForm, file: e.target.value })}
                    placeholder="e.g. src/flask/app.py" style={inputStyle} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                  <div>
                    <label style={labelStyle}>Line Start</label>
                    <input type="number" value={addNodeForm.line_start} onChange={(e) => setAddNodeForm({ ...addNodeForm, line_start: e.target.value })}
                      style={inputStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Line End</label>
                    <input type="number" value={addNodeForm.line_end} onChange={(e) => setAddNodeForm({ ...addNodeForm, line_end: e.target.value })}
                      placeholder="Optional" style={inputStyle} />
                  </div>
                </div>
                <div>
                  <label style={labelStyle}>Qualified Name</label>
                  <input type="text" value={addNodeForm.qualified_name} onChange={(e) => setAddNodeForm({ ...addNodeForm, qualified_name: e.target.value })}
                    placeholder="e.g. Flask.my_function" style={inputStyle} />
                </div>
                <div>
                  <label style={labelStyle}>Signature</label>
                  <input type="text" value={addNodeForm.signature} onChange={(e) => setAddNodeForm({ ...addNodeForm, signature: e.target.value })}
                    placeholder="e.g. my_function(self, arg1, arg2)" style={inputStyle} />
                </div>
                <div>
                  <label style={labelStyle}>Docstring</label>
                  <textarea value={addNodeForm.docstring} onChange={(e) => setAddNodeForm({ ...addNodeForm, docstring: e.target.value })}
                    placeholder="Optional description" rows={3}
                    style={{ ...inputStyle, resize: 'vertical', fontFamily: 'var(--font-mono)' }} />
                </div>

                {addNodeStatus && (
                  <div style={{
                    padding: '0.6rem 0.9rem', borderRadius: '6px', fontSize: '0.82rem',
                    background: addNodeStatus.ok ? '#0a1a0a' : '#1a0a0a',
                    border: `1px solid ${addNodeStatus.ok ? '#2a4a2a' : '#4a2a2a'}`,
                    color: addNodeStatus.ok ? '#6aff6a' : '#ff6a6a',
                  }}>
                    {addNodeStatus.msg}
                  </div>
                )}

                <button onClick={handleAddNode}
                  disabled={!addNodeForm.name || !addNodeForm.file}
                  style={{
                    ...btnWhite, width: '100%', padding: '0.7rem',
                    opacity: (!addNodeForm.name || !addNodeForm.file) ? 0.4 : 1,
                    cursor: (!addNodeForm.name || !addNodeForm.file) ? 'not-allowed' : 'pointer',
                  }}>
                  Add Node to Graph
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ─── TAB 3: DIRECTORY ─── */}
        {activeTab === 'directory' && (
          <div className="animate-fade-in" style={panelStyle}>
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem' }}>
              <input type="text" placeholder="Filter by symbol name or file path…" value={dirSearch}
                onChange={(e) => setDirSearch(e.target.value)}
                style={{ ...inputStyle, flex: 1 }} />
              <select value={dirType} onChange={(e) => setDirType(e.target.value)}
                style={{ ...inputStyle, width: 'auto', minWidth: '150px', cursor: 'pointer' }}>
                <option value="">All Node Types</option>
                <option value="File">File</option>
                <option value="Class">Class</option>
                <option value="Function">Function</option>
              </select>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--panel-border)', color: 'var(--text-secondary)', textAlign: 'left' }}>
                    <th style={{ padding: '0.75rem 1rem' }}>Type</th>
                    <th style={{ padding: '0.75rem 1rem' }}>Qualified Symbol</th>
                    <th style={{ padding: '0.75rem 1rem' }}>File</th>
                    <th style={{ padding: '0.75rem 1rem' }}>Lines</th>
                    <th style={{ padding: '0.75rem 1rem' }}>Signature</th>
                  </tr>
                </thead>
                <tbody>
                  {dirNodes.map((n, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid #1a1a1a' }}>
                      <td style={{ padding: '0.65rem 1rem' }}>
                        <span style={{
                          padding: '2px 6px', borderRadius: '4px', fontSize: '0.72rem', fontWeight: 600,
                          background: n.type === 'File' ? '#fff' : n.type === 'Class' ? '#a3a3a3' : '#262626',
                          color: n.type === 'File' ? '#000' : n.type === 'Class' ? '#000' : '#fff',
                        }}>{n.type}</span>
                      </td>
                      <td style={{ padding: '0.65rem 1rem', fontFamily: 'var(--font-mono)', color: '#fff' }}>{n.qualified_name || n.name}</td>
                      <td style={{ padding: '0.65rem 1rem', color: 'var(--text-secondary)' }}>{n.file}</td>
                      <td style={{ padding: '0.65rem 1rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                        L{n.line_start || 1}{n.line_end ? `–L${n.line_end}` : ''}
                      </td>
                      <td style={{ padding: '0.65rem 1rem', fontFamily: 'var(--font-mono)', fontSize: '0.76rem', color: 'var(--text-muted)' }}>{n.signature || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
