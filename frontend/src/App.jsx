import React, { useEffect, useRef, useState } from 'react'
import { api, evidenceUrl } from './api.js'

const TABS = ['Verify', 'Brands', 'Observations']

// ponytail: hash routing (#/observations/26); no router dep, back/forward and links work natively
const parseHash = () => {
  const [t, id] = window.location.hash.replace(/^#\/?/, '').split('/')
  return { tab: TABS.find((x) => x.toLowerCase() === t) || 'Verify', id: id || null }
}
const hrefFor = (tab, id) => `#/${tab.toLowerCase()}${id ? `/${id}` : ''}`
const go = (tab, id) => { window.location.hash = hrefFor(tab, id) }
function useRoute() {
  const [route, setRoute] = useState(parseHash)
  useEffect(() => {
    const f = () => setRoute(parseHash())
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])
  return route
}

export default function App() {
  const { tab, id } = useRoute()
  const [brands, setBrands] = useState([])
  const [prefill, setPrefill] = useState(null)
  const loadBrands = () => api.brands().then(setBrands).catch(() => setBrands([]))
  useEffect(() => { loadBrands() }, [])

  const editAndRerun = (r) => {
    setPrefill({ brand: r.brand, url: r.product?.url || '', variant: r.requested_variant.options,
                 quantity: r.requested_variant.quantity })
    go('Verify')
  }

  return (
    <div className="app">
      <header>
        <h1>Price check<small>public retail, US, USD</small></h1>
        <nav>{TABS.map((t) => (
          <a key={t} href={hrefFor(t)} className={t === tab ? 'tab on' : 'tab'}
             aria-current={t === tab ? 'page' : undefined}>{t}</a>
        ))}</nav>
      </header>
      {tab === 'Verify' && <Verify brands={brands} prefill={prefill} onEdit={editAndRerun} />}
      {tab === 'Brands' && <Brands brands={brands} reload={loadBrands} />}
      {tab === 'Observations' && <Observations openId={id} onEdit={editAndRerun} />}
    </div>
  )
}

/* ---------------- Verify ---------------- */

// form.variant is a list of [option, value] rows (an object would merge same-named or blank rows)
const toRows = (v) => { const rows = Array.isArray(v) ? v : Object.entries(v || {}); return rows.length ? rows : [['', '']] }

function Verify({ brands, prefill, onEdit }) {
  const blank = { brand: '', url: '', variant: [['', '']], quantity: 1 }
  const [form, setForm] = useState(prefill ? { ...prefill, variant: toRows(prefill.variant) } : blank)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [results, setResults] = useState([])
  useEffect(() => { if (prefill) setForm({ ...prefill, variant: toRows(prefill.variant) }) }, [prefill])

  // busy holds what is being checked (truthy) so the pending card can say it
  const run = async (req, noCache = false) => {
    const variant = Object.fromEntries(toRows(req.variant).filter(([k]) => k.trim()))
    setBusy({ brand: req.brand, what: Object.values(variant).filter(Boolean).join(' / ') || 'no variant given', noCache })
    setErr(null)
    try {
      const r = await api.verify({ ...req, variant, quantity: Number(req.quantity), no_cache: noCache })
      setResults((xs) => [r, ...xs])
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const runInputs = async (noCache) => {
    setBusy({ brand: 'Input file', what: 'every line of inputs.json', noCache }); setErr(null)
    try { const rs = await api.verifyInputs(noCache); setResults((xs) => [...rs, ...xs]) }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const loadInput = async () => {
    const xs = await api.inputs()
    const x = xs.find((i) => i.brand === form.brand) || xs[0]
    if (x) setForm({ brand: x.brand, url: x.url, variant: toRows(x.variant), quantity: x.quantity || 1 })
  }
  const setOpt = (i, k, v) => setForm({ ...form, variant: form.variant.map((row, j) => (j === i ? [k, v] : row)) })
  const removeOpt = (i) => setForm({ ...form, variant: toRows(form.variant.filter((_, j) => j !== i)) })
  const rerun = (r, noCache) => run({ brand: r.brand, url: r.product?.url, variant: r.requested_variant.options,
                                      quantity: r.requested_variant.quantity }, noCache)

  return (
    <section className="verify-grid">
      <aside>
      <div className="card">
        <h2>Verify one variant</h2>
        <label>Brand
          <select value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })}>
            <option value="">choose…</option>
            {/* brand from the input file / an old result that isn't in the brands table: keep it visible */}
            {form.brand && !brands.some((b) => b.name === form.brand) &&
              <option value={form.brand}>{form.brand} (not onboarded)</option>}
            {brands.map((b) => <option key={b.id} value={b.name}>{b.name} ({b.approach})</option>)}
          </select>
        </label>
        <label>Product URL
          <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" />
        </label>
        <div className="opts">
          <span className="lbl">Variant options</span>
          {form.variant.map(([k, v], i) => (
            <div key={i} className="row">
              <input value={k} placeholder="option (e.g. Size)" aria-label={`Option ${i + 1} name`}
                     onChange={(e) => setOpt(i, e.target.value, v)} />
              <input value={v} placeholder='value (e.g. 103"W)' aria-label={`Option ${i + 1} value`}
                     onChange={(e) => setOpt(i, k, e.target.value)} />
              <button className="remove" title="Remove this option" aria-label={`Remove option ${k || i + 1}`}
                      disabled={form.variant.length === 1 && !k && !v} onClick={() => removeOpt(i)}>×</button>
            </div>
          ))}
          <button className="link" onClick={() => setForm({ ...form, variant: [...form.variant, ['', '']] })}>+ option</button>
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
      </aside>

      <main>
        {busy && <Pending job={busy} />}
        {err && <p className="error">{err}</p>}
        {!busy && !err && !results.length &&
          <div className="empty">Verify a variant or run the input file. Results appear here, newest first.</div>}
        {results.map((r, i) => (
          <ResultCard key={results.length - i} r={r} onRerun={(nc) => rerun(r, nc)} onEdit={() => onEdit(r)} />
        ))}
      </main>
    </section>
  )
}

const EST_SECS = 30  // ponytail: fixed estimate from observed browser lookups; per-brand p50 if it misleads

function Pending({ job }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => { const t = setInterval(() => setSecs((x) => x + 1), 1000); return () => clearInterval(t) }, [])
  const over = secs > EST_SECS
  const C = 2 * Math.PI * 34
  return (
    <div className={`card result pending${over ? ' over' : ''}`} role="status" aria-live="polite"
         aria-label={`Checking ${job.brand}`}>
      <div className="tag">
        <div className="ghost">
          <div className="ghost-amt" />
          <div className="ghost-line" />
        </div>
        <div className="who">
          <div className="badges"><span className="badge checking">checking</span>
            {job.noCache && <span className="badge cache">skipping cache</span>}</div>
          <strong>{job.brand}</strong>
          <span className="muted">{job.what}</span>
        </div>
      </div>
      <div className="body pending-body">
        <svg className="ring" viewBox="0 0 80 80" aria-hidden="true">
          <circle cx="40" cy="40" r="34" className="ring-track" />
          <circle cx="40" cy="40" r="34" className="ring-fill" strokeDasharray={C}
                  strokeDashoffset={over ? 0 : C * (secs / EST_SECS)} />
          <text x="40" y="40" className="ring-num">{over ? `+${secs - EST_SECS}` : EST_SECS - secs}</text>
          <text x="40" y="56" className="ring-unit">{over ? 'over' : 'sec'}</text>
        </svg>
        <div>
          <strong>{over ? 'Taking longer than usual' : 'Looking up the live price'}</strong>
          <p className="muted">{over
            ? 'Retries, slow pages or bot checks add time. The result, or an unresolved reason, will still land here.'
            : `Opening the product page and selecting this exact variant. Most checks finish within ${EST_SECS}s.`}</p>
        </div>
      </div>
    </div>
  )
}

function ResultCard({ r, onRerun, onEdit }) {
  const [raw, setRaw] = useState(false)
  const o = r.outcome
  const pb = r.price_basis
  return (
    <div className={`card result ${o.status}`}>
      <div className="tag">
        <div>
          {r.current_amount
            ? <div className="amt"><span className="cur">{r.currency}</span>{r.current_amount}
                {pb.on_sale && pb.compare_at_amount && <s>{pb.compare_at_amount}</s>}</div>
            : <div className="reason">{o.status === 'unresolved' ? (o.reason || 'unresolved').replace(/_/g, ' ') : 'Amount unknown'}</div>}
          <div className="muted">{r.current_amount ? <>{pb.type.replace(/_/g, ' ')}{pb.on_sale && ', on sale'}</>
            : 'No price established; nothing was substituted'}</div>
        </div>
        <div className="who">
          <div className="badges">
            <span className={`badge ${o.status}`}>{o.status}</span>
            {o.from_cache && <span className="badge cache">from cache</span>}
          </div>
          <strong>{r.brand}</strong>
          <span className="muted">{r.product?.title || shortUrl(r.product?.url || '')}</span>
        </div>
      </div>
      <div className="body">
      {o.status === 'unresolved' && o.detail && <Detail d={o.detail} />}
      <h3>Lookup</h3>
      <dl>
        <dt>Product</dt><dd>{r.product?.url
          ? <a href={r.product.url} target="_blank" rel="noreferrer">{shortUrl(r.product.url)}</a> : '—'}</dd>
        <dt>Requested variant</dt><dd>{Object.entries(r.requested_variant.options || {}).map(([k, v]) =>
          <span key={k} className="chip">{k}: {v}</span>)} <span className="muted">× {r.requested_variant.quantity}</span></dd>
        {r.requested_variant.resolved_variant_id && <><dt>Matched variant id</dt>
          <dd className="num">{r.requested_variant.resolved_variant_id}</dd></>}
        {pb.type !== 'unknown' && <><dt>Price basis</dt><dd>{pb.type}{pb.on_sale &&
          <>, on sale, compare-at <s>{r.currency} {pb.compare_at_amount}</s></>}</dd></>}
        {pb.conditions?.length > 0 && <><dt>Conditions seen</dt><dd>{pb.conditions.map((c, i) =>
          <div key={i}><code>{c.type}</code> {c.excerpt || ''}</div>)}</dd></>}
        {(r.market || r.currency) && <><dt>Market</dt><dd>{r.market || '?'}, {r.currency || '?'}</dd></>}
        {r.source?.method && <><dt>Source</dt><dd><code>{r.source.method}</code>
          {r.source.attempts > 1 && <span className="muted"> after {r.source.attempts} attempts</span>}</dd></>}
        {r.source?.cross_check && <><dt>Cross-check</dt><dd>
          <span className={`badge ${r.source.cross_check.agrees ? 'resolved' : 'unresolved'}`}>
            {r.source.cross_check.agrees ? 'agrees' : 'disagrees'}</span>{' '}
          <code>{r.source.cross_check.method}</code> read {r.currency} {String(r.source.cross_check.amount)}</dd></>}
        <dt>Observed</dt><dd className="num">{fmtTime(r.observation_time)}</dd>
        <dt>Run</dt><dd className="num muted">{o.run_id}</dd>
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
    </div>
  )
}

const DETAIL_LABELS = { note: 'Note', error: 'Error', attempts: 'Attempts', scope: 'Scope', resume: 'Resumes',
  retry_after_seconds: 'Retry after', requested: 'Requested', valid_options: 'Valid options' }

// outcome.detail is free-form per reason; render known shapes, never a raw JSON dump
function Detail({ d }) {
  const { handoff, ...rest } = d
  const val = (k, v) => {
    if (k.endsWith('_seconds') && typeof v === 'number') return fmtDuration(v)
    if (Array.isArray(v)) return v.map((x, i) => <span key={i} className="chip">{String(x)}</span>)
    if (v && typeof v === 'object') return Object.entries(v).map(([ok, ov]) => (
      <div key={ok} className="opt-line"><span className="muted">{ok}</span>
        {(Array.isArray(ov) ? ov : [ov]).map((x, i) => <span key={i} className="chip">{String(x)}</span>)}</div>))
    return String(v)
  }
  return (
    <div className="why">
      <h3>Why it's unresolved</h3>
      <dl>{Object.entries(rest).map(([k, v]) => (
        <React.Fragment key={k}><dt>{DETAIL_LABELS[k] || k.replace(/_/g, ' ')}</dt><dd>{val(k, v)}</dd></React.Fragment>
      ))}</dl>
      {handoff && <div className="handoff"><strong>Ops action</strong><p>{String(handoff).replace(/^ops:\s*/, '')}</p></div>}
    </div>
  )
}

function Evidence({ items }) {
  const [viewing, setViewing] = useState(null)
  if (!items?.length) return <p className="muted ev-none">No evidence captured.</p>
  const shots = items.filter((e) => e.kind === 'screenshot' && e.path)
  return (
    <div className="evidence">
      <h3>Evidence <span className="muted">{items.length} items</span></h3>
      <ol className="ev-list">{items.map((e, i) => (
        <li key={i}>
          <div className="ev-head">
            <code>{e.kind}</code>
            {e.recorded && <span className="badge cache">recorded</span>}
            {e.path && <a href={evidenceUrl(e.path)} target="_blank" rel="noreferrer">{e.path.split('/').pop()}</a>}
            {e.captured_at && <span className="muted num ev-time">{fmtTime(e.captured_at, true)}</span>}
          </div>
          {e.excerpt && <div className="ev-excerpt">{e.excerpt}</div>}
        </li>
      ))}</ol>
      {shots.length > 0 && <div className="shots">{shots.map((e, i) => (
        <a key={i} href={evidenceUrl(e.path)} target="_blank" rel="noreferrer" onClick={(ev) => {
          if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return  // keep new-tab clicks native
          ev.preventDefault(); setViewing(e)
        }}>
          <img src={evidenceUrl(e.path)} alt={`Page screenshot ${e.path.split('/').pop()}`} /></a>
      ))}</div>}
      {viewing && <Viewer e={viewing} onClose={() => setViewing(null)} />}
    </div>
  )
}

// native <dialog>: Esc, focus trap and backdrop come free
function Viewer({ e, onClose }) {
  const ref = useRef(null)
  useEffect(() => { ref.current.showModal() }, [])
  const url = evidenceUrl(e.path), name = e.path.split('/').pop()
  return (
    <dialog ref={ref} className="viewer" onClose={onClose}
            onClick={(ev) => ev.target === ref.current && ref.current.close()}>
      <div className="viewer-bar">
        <strong>{name}</strong>
        {e.captured_at && <span className="muted num">captured {fmtTime(e.captured_at)}</span>}
        <a href={url} target="_blank" rel="noreferrer">Open in new tab</a>
        <button className="secondary" autoFocus onClick={() => ref.current.close()}>Close</button>
      </div>
      <iframe src={url} title={`Screenshot ${name}`} />
    </dialog>
  )
}

const fmtOpts = (o) => Object.entries(o || {}).map(([k, v]) => `${k}: ${v}`).join(', ')
const fmtTime = (iso, timeOnly) => {
  const d = new Date(iso)
  if (isNaN(d)) return iso || '—'
  return timeOnly ? d.toLocaleTimeString() : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' })
}
const fmtDuration = (s) => (s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
  : s >= 60 ? `${Math.round(s / 60)}m` : `${s}s`)
const fmtDate = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) }
const fmtMoney = (amt, cur) => { try { return new Intl.NumberFormat('en-US', { style: 'currency', currency: cur || 'USD' }).format(Number(amt)) } catch { return `${cur} ${amt}` } }
// product name from the URL slug when the lookup never got a title (skip numeric ids like /1358963)
const shortPath = (u) => {
  try { const seg = new URL(u).pathname.split('/').filter((x) => x && !/^\d+$/.test(x)).pop() || ''; return seg.replace(/-/g, ' ') }
  catch { return u || '' }
}
const shortUrl = (u) => { try { const x = new URL(u); return x.hostname.replace(/^www\./, '') + x.pathname } catch { return u } }

/* ---------------- Brands / onboarding ---------------- */

function Brands({ brands, reload }) {
  const [f, setF] = useState({ name: '', domain: '', sample_url: '' })
  const [proposal, setProposal] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [adapters, setAdapters] = useState([])
  useEffect(() => { api.adapters().then(setAdapters).catch(() => setAdapters([])) }, [])
  // adapter = module in backend/pricecheck/brands; empty = no_adapter (ops verifies by hand)
  const adapterSelect = (value, onChange) => (
    <select value={value || ''} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">none → no_adapter</option>
      {adapters.map((a) => <option key={a}>{a}</option>)}
    </select>
  )

  const doProbe = async () => {
    setBusy(true); setErr(null); setProposal(null)
    try { setProposal({ ...(await api.probe(f)), name: f.name }) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const save = async () => {
    setErr(null)
    try {
      const { signals, ...b } = proposal
      await api.saveBrand({ ...b, probe_evidence: { ...b.probe_evidence, signals }, config: b.config || {} })
      setProposal(null); setF({ name: '', domain: '', sample_url: '' }); reload()
    } catch (e) { setErr(e.message) }
  }
  const patch = async (id, p) => { await api.patchBrand(id, p); reload() }

  return (
    <section>
      <div className="card">
        <h2>Brands</h2>
        <div className="scroll"><table>
          <thead><tr><th>Name</th><th>Domain</th><th>Approach</th><th>Custom method</th><th>Adapter</th><th>UCP</th><th>Status</th></tr></thead>
          <tbody>{brands.map((b) => (
            <tr key={b.id}>
              <td>{b.name}</td><td>{b.domain}</td><td><code>{b.approach}</code></td>
              <td>{b.custom_method || '—'}</td>
              <td>{adapterSelect(b.adapter, (adapter) => patch(b.id, { adapter }))}</td>
              <td>{b.ucp_endpoint ? 'yes' : 'no'}</td>
              <td>
                <select value={b.status} onChange={(e) => patch(b.id, { status: e.target.value })}>
                  {['live', 'disabled'].map((s) => <option key={s}>{s}</option>)}
                </select>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
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
            <label>Adapter{adapterSelect(proposal.adapter, (adapter) => setProposal({ ...proposal, adapter }))}</label>
            <p>UCP: {proposal.ucp_endpoint || 'no'}</p>
            <p className="muted">Proposed config: <code>{JSON.stringify(proposal.config || {})}</code></p>
            <details><summary>Probe evidence</summary><pre>{JSON.stringify(proposal.probe_evidence, null, 2)}</pre></details>
            <div className="actions"><button onClick={save}>Save brand</button></div>
          </div>
        )}
      </div>
    </section>
  )
}

/* ---------------- Observations / ops view ---------------- */

function Observations({ openId, onEdit }) {
  const [rows, setRows] = useState([])
  const [onlyUnresolved, setOnly] = useState(false)
  const open = rows.find((r) => String(r._id) === openId) || null
  const setOpen = (r) => go('Observations', r?._id)
  useEffect(() => { api.observations(onlyUnresolved ? 'unresolved' : '').then(setRows).catch(() => setRows([])) }, [onlyUnresolved])

  return (
    <section className={open ? 'obs-grid' : ''}>
      <div className="card">
        <div className="toolbar">
          <h2>Observations <span className="muted">{rows.length}</span></h2>
          <label className="inline"><input type="checkbox" checked={onlyUnresolved} onChange={(e) => setOnly(e.target.checked)} />
            Only unresolved (ops queue)</label>
        </div>
        {!rows.length && <div className="empty">No observations yet. Run a check from the Verify tab.</div>}
        {rows.length > 0 && <div className="scroll"><table className={`obs${open ? ' compact' : ''}`}>
          <colgroup><col className="c-dot" /><col className="c-prod" /><col className="c-var" /><col className="c-res" />
            <col className="c-when" /><col className="c-src src" /></colgroup>
          <thead><tr><th aria-label="Status" /><th>Product</th><th>Variant</th><th className="r">Result</th>
            <th className="r">Observed</th><th className="src">Source</th></tr></thead>
          <tbody>{rows.map((r) => {
            const ok = r.outcome.status === 'resolved', variant = Object.values(r.requested_variant.options || {}).join(' / ')
            return (
            <tr key={r._id} className={open?._id === r._id ? 'click on' : 'click'} tabIndex={0}
                aria-selected={open?._id === r._id}
                onClick={() => setOpen(r)} onKeyDown={(e) => e.key === 'Enter' && setOpen(r)}>
              <td><span className={`dot ${r.outcome.status}`} title={r.outcome.status} /></td>
              <td><div className="clip"><strong>{r.brand}</strong></div>
                <div className="clip muted">{r.product?.title || shortPath(r.product?.url)}</div></td>
              <td><div className="clip" title={fmtOpts(r.requested_variant.options)}>{variant}</div></td>
              <td className="r">{ok ? <span className="num amt-cell">{fmtMoney(r.current_amount, r.currency)}</span>
                : <span className="why-cell">{(r.outcome.reason || 'unresolved').replace(/_/g, ' ')}</span>}</td>
              <td className="r num muted when" title={r.observation_time}>{fmtDate(r.observation_time)}, {fmtTime(r.observation_time, true)}</td>
              <td className="src"><div className="clip muted">{r.source?.method || '—'}</div></td>
            </tr>)
          })}</tbody>
        </table></div>}
      </div>
      {open && <aside className="side">
        <button className="close" aria-label="Close details" onClick={() => setOpen(null)}>×</button>
        <ResultCard r={open} onRerun={() => onEdit(open)} onEdit={() => onEdit(open)} />
      </aside>}
    </section>
  )
}
