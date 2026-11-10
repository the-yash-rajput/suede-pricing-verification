import React, { useEffect, useState } from 'react'
import { api, evidenceUrl } from './api.js'

const TABS = ['Verify', 'Brands', 'Observations']

export default function App() {
  const [tab, setTab] = useState('Verify')
  const [brands, setBrands] = useState([])
  const [prefill, setPrefill] = useState(null)
  const loadBrands = () => api.brands().then(setBrands).catch(() => setBrands([]))
  useEffect(() => { loadBrands() }, [])

  const editAndRerun = (r) => {
    setPrefill({ brand: r.brand, url: r.product?.url || '', variant: r.requested_variant.options,
                 quantity: r.requested_variant.quantity })
    setTab('Verify')
  }

  return (
    <div className="app">
      <header>
        <h1>Price verification</h1>
        <nav>{TABS.map((t) => (
          <button key={t} className={t === tab ? 'tab on' : 'tab'} onClick={() => setTab(t)}>{t}</button>
        ))}</nav>
      </header>
      {tab === 'Verify' && <Verify brands={brands} prefill={prefill} onEdit={editAndRerun} />}
      {tab === 'Brands' && <Brands brands={brands} reload={loadBrands} />}
      {tab === 'Observations' && <Observations onEdit={editAndRerun} />}
    </div>
  )
}

/* ---------------- Verify ---------------- */

function Verify({ brands, prefill, onEdit }) {
  const blank = { brand: '', url: '', variant: { '': '' }, quantity: 1 }
  const [form, setForm] = useState(prefill || blank)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [results, setResults] = useState([])
  useEffect(() => { if (prefill) setForm(prefill) }, [prefill])

  const run = async (req, noCache = false) => {
    setBusy(true); setErr(null)
    try {
      const variant = Object.fromEntries(Object.entries(req.variant).filter(([k]) => k.trim()))
      const r = await api.verify({ ...req, variant, quantity: Number(req.quantity), no_cache: noCache })
      setResults((xs) => [r, ...xs])
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const runInputs = async (noCache) => {
    setBusy(true); setErr(null)
    try { const rs = await api.verifyInputs(noCache); setResults((xs) => [...rs, ...xs]) }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const loadInput = async () => {
    const xs = await api.inputs()
    const x = xs.find((i) => i.brand === form.brand) || xs[0]
    if (x) setForm({ brand: x.brand, url: x.url, variant: x.variant, quantity: x.quantity || 1 })
  }
  const setOpt = (i, k, v) => {
    const entries = Object.entries(form.variant)
    entries[i] = [k, v]
    setForm({ ...form, variant: Object.fromEntries(entries) })
  }
  const rerun = (r, noCache) => run({ brand: r.brand, url: r.product?.url, variant: r.requested_variant.options,
                                      quantity: r.requested_variant.quantity }, noCache)

  return (
    <section>
      <div className="card">
        <h2>Verify one variant</h2>
        <label>Brand
          <select value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })}>
            <option value="">choose…</option>
            {brands.map((b) => <option key={b.id} value={b.name}>{b.name} ({b.approach})</option>)}
          </select>
        </label>
        <label>Product URL
          <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" />
        </label>
        <div className="opts">
          <span className="lbl">Variant options</span>
          {Object.entries(form.variant).map(([k, v], i) => (
            <div key={i} className="row">
              <input value={k} placeholder="option (e.g. Size)" onChange={(e) => setOpt(i, e.target.value, v)} />
              <input value={v} placeholder='value (e.g. 103"W)' onChange={(e) => setOpt(i, k, e.target.value)} />
            </div>
          ))}
          <button className="link" onClick={() => setForm({ ...form, variant: { ...form.variant, '': '' } })}>+ option</button>
        </div>
        <label className="qty">Quantity
          <input type="number" min="1" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
        </label>
        <div className="actions">
          <button disabled={busy || !form.brand || !form.url} onClick={() => run(form)}>Verify</button>
          <button disabled={busy || !form.brand || !form.url} onClick={() => run(form, true)}>Verify fresh (skip cache)</button>
          <button className="secondary" onClick={loadInput}>Load from input file</button>
        </div>
      </div>

      <div className="card">
        <h2>Input file</h2>
        <p className="muted">Runs every line of <code>inputs.json</code>: the "aging proposal → refresh" path.</p>
        <div className="actions">
          <button disabled={busy} onClick={() => runInputs(false)}>Run input file</button>
          <button disabled={busy} onClick={() => runInputs(true)}>Run fresh</button>
        </div>
      </div>

      {busy && <p className="muted">Checking… browser lookups take 10–30s.</p>}
      {err && <p className="error">{err}</p>}
      {results.map((r, i) => (
        <ResultCard key={i} r={r} onRerun={(nc) => rerun(r, nc)} onEdit={() => onEdit(r)} />
      ))}
    </section>
  )
}

function ResultCard({ r, onRerun, onEdit }) {
  const [raw, setRaw] = useState(false)
  const o = r.outcome
  const pb = r.price_basis
  return (
    <div className={`card result ${o.status}`}>
      <div className="head">
        <span className={`badge ${o.status}`}>{o.status}</span>
        {o.from_cache && <span className="badge cache">from cache</span>}
        <strong>{r.brand}</strong> · {r.product?.title || r.product?.url}
      </div>
      <dl>
        <dt>Requested variant</dt><dd>{fmtOpts(r.requested_variant.options)} × {r.requested_variant.quantity}
          {r.requested_variant.resolved_variant_id && <span className="muted"> (id {r.requested_variant.resolved_variant_id})</span>}</dd>
        <dt>Current amount</dt><dd className="amt">{r.current_amount ? `${r.currency} ${r.current_amount}` : '— unknown'}</dd>
        <dt>Price basis</dt><dd>{pb.type}{pb.on_sale && <> · on sale, compare-at <s>{r.currency} {pb.compare_at_amount}</s></>}</dd>
        {pb.conditions?.length > 0 && <><dt>Conditions seen</dt><dd>{pb.conditions.map((c, i) =>
          <div key={i}><code>{c.type}</code> {c.excerpt || ''}</div>)}</dd></>}
        <dt>Market / currency</dt><dd>{r.market || '?'} / {r.currency || '?'}</dd>
        <dt>Source</dt><dd>{r.source?.method || '—'}{r.source?.cross_check &&
          <> · cross-check {r.source.cross_check.method}: {String(r.source.cross_check.amount)} ({r.source.cross_check.agrees ? 'agrees' : 'DISAGREES'})</>}</dd>
        <dt>Observed</dt><dd>{r.observation_time} <span className="muted">run {o.run_id}</span></dd>
        {o.status === 'unresolved' && <><dt>Reason</dt><dd className="error">{o.reason}
          {o.detail && <pre>{JSON.stringify(o.detail, null, 2)}</pre>}</dd></>}
      </dl>
      <Evidence items={r.supporting_evidence} />
      <div className="actions">
        <button onClick={() => onRerun(false)}>Rerun</button>
        <button onClick={() => onRerun(true)}>Rerun fresh</button>
        <button className="secondary" onClick={onEdit}>Edit &amp; rerun</button>
        <button className="link" onClick={() => setRaw(!raw)}>{raw ? 'hide' : 'show'} JSON</button>
      </div>
      {raw && <pre>{JSON.stringify(r, null, 2)}</pre>}
    </div>
  )
}

function Evidence({ items }) {
  if (!items?.length) return <p className="muted">No evidence captured.</p>
  return (
    <div className="evidence">
      {items.map((e, i) => (
        <div key={i} className="ev">
          <code>{e.kind}</code>{e.recorded && <span className="badge">recorded</span>}
          {e.path && <a href={evidenceUrl(e.path)} target="_blank" rel="noreferrer">{e.path.split('/').pop()}</a>}
          {e.excerpt && <span className="muted"> {e.excerpt}</span>}
          {e.kind === 'screenshot' && e.path && <img src={evidenceUrl(e.path)} alt="page screenshot" />}
        </div>
      ))}
    </div>
  )
}

const fmtOpts = (o) => Object.entries(o || {}).map(([k, v]) => `${k}: ${v}`).join(', ')

/* ---------------- Brands / onboarding ---------------- */

function Brands({ brands, reload }) {
  const [f, setF] = useState({ name: '', domain: '', sample_url: '' })
  const [proposal, setProposal] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const doProbe = async () => {
    setBusy(true); setErr(null); setProposal(null)
    try { setProposal({ ...(await api.probe(f)), name: f.name }) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const save = async () => {
    setErr(null)
    try {
      const { signals, ...b } = proposal
      await api.saveBrand({ ...b, probe_evidence: { ...b.probe_evidence, signals }, config: {} })
      setProposal(null); setF({ name: '', domain: '', sample_url: '' }); reload()
    } catch (e) { setErr(e.message) }
  }
  const patch = async (id, p) => { await api.patchBrand(id, p); reload() }

  return (
    <section>
      <div className="card">
        <h2>Brands</h2>
        <table>
          <thead><tr><th>Name</th><th>Domain</th><th>Approach</th><th>Custom method</th><th>Adapter</th><th>UCP</th><th>Status</th></tr></thead>
          <tbody>{brands.map((b) => (
            <tr key={b.id}>
              <td>{b.name}</td><td>{b.domain}</td><td><code>{b.approach}</code></td>
              <td>{b.custom_method || '—'}</td>
              <td>{b.adapter || <span className="error">none → no_adapter</span>}</td>
              <td>{b.ucp_endpoint ? 'yes' : 'no'}</td>
              <td>
                <select value={b.status} onChange={(e) => patch(b.id, { status: e.target.value })}>
                  {['onboarding', 'live', 'disabled'].map((s) => <option key={s}>{s}</option>)}
                </select>
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>

      <div className="card">
        <h2>Onboard a brand</h2>
        <p className="muted">Shopify (with or without UCP) → generic adapter, no code. Anything else → <code>custom</code>,
          unresolved (<code>no_adapter</code>) until an engineer builds its adapter.</p>
        <label>Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label>Domain<input value={f.domain} placeholder="www.example.com" onChange={(e) => setF({ ...f, domain: e.target.value })} /></label>
        <label>Sample product URL<input value={f.sample_url} onChange={(e) => setF({ ...f, sample_url: e.target.value })} /></label>
        <div className="actions"><button disabled={busy || !f.name || !f.domain || !f.sample_url} onClick={doProbe}>
          {busy ? 'Probing…' : 'Probe'}</button></div>
        {err && <p className="error">{err}</p>}
        {proposal && (
          <div className="proposal">
            <h3>Probe proposal: review before saving</h3>
            <ul>{proposal.signals.map((s, i) => <li key={i}>{s}</li>)}</ul>
            <label>Approach
              <select value={proposal.approach} onChange={(e) => {
                const approach = e.target.value
                setProposal({ ...proposal, approach, adapter: approach === 'custom' ? null : 'shopify' })
              }}>
                {['shopify_ucp', 'shopify', 'custom'].map((a) => <option key={a}>{a}</option>)}
              </select>
            </label>
            {proposal.approach === 'custom' && (
              <label>Custom method
                <select value={proposal.custom_method || 'manual'} onChange={(e) => setProposal({ ...proposal, custom_method: e.target.value })}>
                  {['page_structured', 'site_api', 'browser', 'manual'].map((m) => <option key={m}>{m}</option>)}
                </select>
              </label>
            )}
            <p>Adapter: <code>{proposal.adapter || 'none yet'}</code> · UCP: {proposal.ucp_endpoint || 'no'}</p>
            <details><summary>Probe evidence</summary><pre>{JSON.stringify(proposal.probe_evidence, null, 2)}</pre></details>
            <div className="actions"><button onClick={save}>Save brand</button></div>
          </div>
        )}
      </div>
    </section>
  )
}

/* ---------------- Observations / ops view ---------------- */

function Observations({ onEdit }) {
  const [rows, setRows] = useState([])
  const [onlyUnresolved, setOnly] = useState(false)
  const [open, setOpen] = useState(null)
  useEffect(() => { api.observations(onlyUnresolved ? 'unresolved' : '').then(setRows).catch(() => setRows([])) }, [onlyUnresolved])

  return (
    <section>
      <div className="card">
        <h2>Observations</h2>
        <label className="inline"><input type="checkbox" checked={onlyUnresolved} onChange={(e) => setOnly(e.target.checked)} />
          only unresolved (ops queue)</label>
        <table>
          <thead><tr><th>Observed</th><th>Brand</th><th>Variant</th><th>Outcome</th><th>Amount</th><th>Source</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r._id} className="click" onClick={() => setOpen(r)}>
              <td>{r.observation_time}</td><td>{r.brand}</td><td>{fmtOpts(r.requested_variant.options)}</td>
              <td><span className={`badge ${r.outcome.status}`}>{r.outcome.status}</span> {r.outcome.reason || ''}</td>
              <td>{r.current_amount ? `${r.currency} ${r.current_amount}` : '—'}</td><td>{r.source?.method}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {open && <ResultCard r={open} onRerun={() => onEdit(open)} onEdit={() => onEdit(open)} />}
    </section>
  )
}
