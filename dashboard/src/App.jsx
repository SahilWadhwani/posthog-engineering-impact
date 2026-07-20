import React, { useEffect, useMemo, useState } from "react";

const DIM_COLORS = {
  scope: "#5b8def",
  criticality: "#f5533d",
  review: "#17b3a3",
  centrality: "#f2a900",
  reliability: "#37c26a",
  consistency: "#a56bff",
};

const DIM_SHORT = {
  scope: "Scope",
  criticality: "Criticality",
  review: "Reviews",
  centrality: "Collaboration",
  reliability: "Reliability",
  consistency: "Consistency",
};

function useData() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    fetch("./data.json")
      .then((r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);
  return { data, err };
}

/* ---------- SVG radar chart (no chart library => tiny, instant load) ---------- */
function Radar({ dimensions, scores, size = 260 }) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 34;
  const n = dimensions.length;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const point = (i, val) => {
    const rad = (val / 100) * r;
    return [cx + rad * Math.cos(angle(i)), cy + rad * Math.sin(angle(i))];
  };
  const rings = [25, 50, 75, 100];
  const polygon = dimensions.map((d, i) => point(i, scores[d.key]).join(",")).join(" ");
  return (
    <svg viewBox={`-52 -6 ${size + 104} ${size + 12}`} width={size} height={size} className="radar">
      {rings.map((ring) => (
        <polygon
          key={ring}
          points={dimensions.map((d, i) => point(i, ring).join(",")).join(" ")}
          className="radar-ring"
        />
      ))}
      {dimensions.map((d, i) => {
        const [x, y] = point(i, 100);
        return <line key={d.key} x1={cx} y1={cy} x2={x} y2={y} className="radar-axis" />;
      })}
      <polygon points={polygon} className="radar-area" />
      {dimensions.map((d, i) => {
        const [x, y] = point(i, scores[d.key]);
        return <circle key={d.key} cx={x} cy={y} r={3.5} fill={DIM_COLORS[d.key]} />;
      })}
      {dimensions.map((d, i) => {
        const [x, y] = point(i, 116);
        return (
          <text
            key={d.key}
            x={x}
            y={y}
            className="radar-label"
            textAnchor={Math.abs(x - cx) < 6 ? "middle" : x > cx ? "start" : "end"}
          >
            {DIM_SHORT[d.key]}
          </text>
        );
      })}
    </svg>
  );
}

function ScoreBar({ dim, value }) {
  return (
    <div className="bar-row" title={dim.desc}>
      <span className="bar-label">{dim.label}</span>
      <span className="bar-track">
        <span
          className="bar-fill"
          style={{ width: `${value}%`, background: DIM_COLORS[dim.key] }}
        />
      </span>
      <span className="bar-val">{Math.round(value)}</span>
    </div>
  );
}

function Avatar({ e, size = 54 }) {
  const [ok, setOk] = useState(true);
  if (e.avatar && ok) {
    return (
      <img
        className="avatar"
        src={e.avatar}
        width={size}
        height={size}
        alt={e.login || e.name}
        onError={() => setOk(false)}
      />
    );
  }
  const initials = (e.name || e.login || "?")
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <span className="avatar avatar-fallback" style={{ width: size, height: size }}>
      {initials}
    </span>
  );
}

function Detail({ e, dimensions }) {
  return (
    <div className="detail">
      <div className="detail-head">
        <Avatar e={e} size={60} />
        <div className="detail-id">
          <div className="detail-name">
            {e.name}
            {e.login && (
              <a className="gh" href={e.profile} target="_blank" rel="noreferrer">
                @{e.login}
              </a>
            )}
          </div>
          <div className="detail-sig">
            Signature strength: <b>{e.signature}</b>
          </div>
        </div>
        <div className="detail-score">
          <div className="score-num">{e.impact}</div>
          <div className="score-lbl">Impact score</div>
        </div>
      </div>

      <div className="detail-body">
        <div className="detail-left">
          <Radar dimensions={dimensions} scores={e.scores} />
          <div className="raw-stats">
            <span><b>{e.raw.prs}</b> PRs</span>
            <span><b>{e.raw.authors_unblocked}</b> reviewed</span>
            <span><b>{e.raw.areas}</b> areas</span>
            <span><b>{e.raw.active_weeks}</b>/13 wks</span>
            <span><b>{Math.round(e.raw.core_share * 100)}%</b> core code</span>
            <span><b>{e.raw.reverts_against}</b> reverts</span>
          </div>
        </div>

        <div className="detail-right">
          <div className="why">
            <div className="why-title">Why they rank here</div>
            <ul>
              {e.highlights.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          </div>
          <div className="bars">
            {dimensions.map((d) => (
              <ScoreBar key={d.key} dim={d} value={e.scores[d.key]} />
            ))}
          </div>
        </div>
      </div>

      <div className="detail-foot">
        <div className="areas">
          <span className="mini-title">Top areas</span>
          {e.top_areas.map((a) => (
            <span key={a.area} className="chip">
              {a.area} <em>{a.touches}</em>
            </span>
          ))}
        </div>
        <div className="prs">
          <span className="mini-title">Representative PRs (click to verify)</span>
          {e.sample_prs.map((p) => (
            <a key={p.pr} className="pr" href={p.url} target="_blank" rel="noreferrer">
              #{p.pr} {p.title}
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}

function Methodology({ data, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(ev) => ev.stopPropagation()}>
        <div className="modal-head">
          <h2>How the Impact Score is built</h2>
          <button className="x" onClick={onClose}>×</button>
        </div>
        <p className="modal-lead">
          Counting commits or lines of code rewards volume, not impact. We instead score
          five transparent signals and show the raw numbers behind each, so every ranking
          can be validated. All data is derived from the complete squash-merge history of{" "}
          <b>{data.meta.repo}</b> over the last <b>{data.meta.window_days} days</b> (
          {data.meta.window_start} → {data.meta.window_end}):{" "}
          <b>{data.meta.total_prs.toLocaleString()}</b> merged PRs across{" "}
          <b>{data.meta.total_engineers}</b> contributors.
        </p>
        <div className="dim-table">
          {data.dimensions.map((d) => (
            <div className="dim-row" key={d.key}>
              <span className="dim-swatch" style={{ background: DIM_COLORS[d.key] }} />
              <div>
                <div className="dim-name">
                  {d.label} <span className="dim-w">weight {d.weight}%</span>
                </div>
                <div className="dim-desc">{d.desc}</div>
              </div>
            </div>
          ))}
        </div>
        <p className="modal-note">
          Count-based signals (Scope, Criticality, Review Leverage, Collaboration) are
          normalised to a 0–100 <b>percentile rank</b> among the{" "}
          {data.meta.qualified_engineers} engineers with ≥ {data.meta.qualify_threshold_prs}{" "}
          merged PRs; Reliability and Consistency use direct formulas. Impact = weighted
          average of the six. Bots and automated accounts are excluded.
        </p>
        <p className="modal-note dim">{data.meta.review_note}</p>
      </div>
    </div>
  );
}

export default function App() {
  const { data, err } = useData();
  const [selected, setSelected] = useState(0);
  const [showMethod, setShowMethod] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const top5 = useMemo(() => (data ? data.engineers.slice(0, 5) : []), [data]);

  if (err) return <div className="loading">Could not load data: {err}</div>;
  if (!data) return <div className="loading">Loading impact analysis…</div>;

  const e = data.engineers[selected];

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>
            Most impactful engineers at <span className="ph">PostHog</span>
          </h1>
          <p className="sub">
            Last {data.meta.window_days} days · {data.meta.total_prs.toLocaleString()} merged
            PRs · {data.meta.total_engineers} contributors · ranked by a 6-signal impact
            model — <button className="link" onClick={() => setShowMethod(true)}>how it works</button>
          </p>
        </div>
        <button className="method-btn" onClick={() => setShowMethod(true)}>
          Methodology
        </button>
      </header>

      <main className="grid">
        <section className="leaderboard">
          <div className="lb-title">Top 5</div>
          {top5.map((eng, i) => (
            <button
              key={eng.key}
              className={"lb-card" + (i === selected ? " active" : "")}
              onClick={() => setSelected(i)}
            >
              <span className="lb-rank">{eng.rank}</span>
              <Avatar e={eng} size={38} />
              <span className="lb-info">
                <span className="lb-name">{eng.login || eng.name}</span>
                <span className="lb-sig">{eng.signature}</span>
              </span>
              <span className="lb-score">{eng.impact}</span>
            </button>
          ))}
          <button className="all-btn" onClick={() => setShowAll((s) => !s)}>
            {showAll ? "Hide" : "See"} full ranking ({data.engineers.length})
          </button>
        </section>

        <section className="stage">
          <Detail e={e} dimensions={data.dimensions} />
        </section>
      </main>

      {showAll && (
        <div className="modal-backdrop" onClick={() => setShowAll(false)}>
          <div className="modal wide" onClick={(ev) => ev.stopPropagation()}>
            <div className="modal-head">
              <h2>Full ranking · {data.engineers.length} qualified engineers</h2>
              <button className="x" onClick={() => setShowAll(false)}>×</button>
            </div>
            <div className="rank-table">
              <div className="rank-head">
                <span>#</span><span>Engineer</span><span>Impact</span>
                <span>Scope</span><span>Critical</span><span>Reviews</span><span>Central</span>
                <span>Reliab.</span><span>Consist.</span><span>PRs</span>
              </div>
              {data.engineers.map((eng) => (
                <div
                  className="rank-row"
                  key={eng.key}
                  onClick={() => {
                    const idx = data.engineers.indexOf(eng);
                    if (idx < 5) setSelected(idx);
                    setShowAll(false);
                  }}
                >
                  <span>{eng.rank}</span>
                  <span className="rr-name">{eng.login || eng.name}</span>
                  <span className="rr-impact">{eng.impact}</span>
                  <span>{Math.round(eng.scores.scope)}</span>
                  <span>{Math.round(eng.scores.criticality)}</span>
                  <span>{Math.round(eng.scores.review)}</span>
                  <span>{Math.round(eng.scores.centrality)}</span>
                  <span>{Math.round(eng.scores.reliability)}</span>
                  <span>{Math.round(eng.scores.consistency)}</span>
                  <span>{eng.raw.prs}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {showMethod && <Methodology data={data} onClose={() => setShowMethod(false)} />}

      <footer className="footer">
        Source: complete <code>git</code> history of {data.meta.repo} ·{" "}
        {data.meta.total_commits_analyzed.toLocaleString()} PR-merge commits analysed ·
        generated {new Date(data.meta.generated_at).toISOString().slice(0, 10)} · every score
        is reproducible from the numbers shown.
      </footer>
    </div>
  );
}
