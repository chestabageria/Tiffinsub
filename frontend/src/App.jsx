import { useEffect, useState } from 'react'
import './index.css'

const API = '/api'
const today = new Date().toISOString().slice(0, 10)
const monthNow = today.slice(0, 7)
const money = value => `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`

async function api(path, options = {}) {
  const token = localStorage.getItem('tiffin_token')
  const response = await fetch(API + path, { ...options, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) } })
  const data = await response.json().catch(() => ({}))
  if (response.status === 401) {
    localStorage.removeItem('tiffin_token')
    localStorage.removeItem('tiffin_role')
    window.location.reload()
    throw Error('Your session expired. Please sign in again.')
  }
  if (!response.ok) throw Error(data.detail || 'Request failed')
  return data
}

function Auth({ mode, customer, back, done }) {
  const [form, setForm] = useState({ name: '', email: '', password: '', phone: '' })
  const [error, setError] = useState('')
  const submit = async event => {
    event.preventDefault()
    try {
      const path = customer ? mode === 'register' ? '/auth/customer/register' : '/auth/login' : mode === 'register' ? '/auth/register' : '/auth/login'
      const body = customer && mode === 'register' ? form : mode === 'register' ? form : { email: form.email, password: form.password }
      const result = await api(path, { method: 'POST', body: JSON.stringify(body) })
      localStorage.setItem('tiffin_token', result.access_token)
      localStorage.setItem('tiffin_role', customer ? 'CUSTOMER' : 'OWNER')
      done()
    } catch (caught) { setError(caught.message) }
  }
  return <main className="auth"><button className="text-button" onClick={back}>← Back</button><form onSubmit={submit}>
    <b className="brand"><i>TL</i> Tiffin Ledger</b><small>{customer ? 'CUSTOMER ACCESS' : 'OWNER ACCESS'}</small>
    <h1>{customer ? 'Join your lunch plan.' : mode === 'register' ? 'Start your ledger.' : 'Welcome back.'}</h1>
    {customer && <label>Phone<input required value={form.phone} onChange={event => setForm({ ...form, phone: event.target.value })} placeholder="The phone on your subscription" /></label>}
    {(!customer && mode === 'register' || customer) && <label>Name<input required value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label>}
    <label>Email<input required type="email" value={form.email} onChange={event => setForm({ ...form, email: event.target.value })} /></label>
    <label>Password<input required minLength="6" type="password" value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} /></label>
    {error && <em>{error}</em>}<button className="primary" type="submit">{customer ? 'Create customer account' : mode === 'register' ? 'Create owner account' : 'Sign in'} →</button>
    {!customer && <button type="button" className="text-button" onClick={() => done(mode === 'register' ? 'login' : 'register')}>{mode === 'register' ? 'Already have an account? Sign in' : 'New owner? Create an account'}</button>}
  </form></main>
}

function Landing({ choose }) {
  return <main className="landing"><nav><b className="brand"><i>TL</i> Tiffin Ledger</b><div><button className="text-button" onClick={() => choose('customer-login')}>Customer sign in</button><button className="primary small-button" onClick={() => choose('login')}>Owner sign in</button></div></nav><section className="hero"><div><small>LUNCH, WITHOUT THE SPREADSHEET</small><h1>Every meal delivered. Every rupee accounted for.</h1><p>A shared tiffin ledger where owners manage service and customers can pause, resume, and understand every bill.</p><button className="primary" onClick={() => choose('customer-register')}>Customer portal →</button></div><aside><small>THIS MONTH</small><strong>22</strong><span>weekday delivery days</span><hr /><small>Plans flex around real life. Your bill does too.</small></aside></section></main>
}

function OwnerDashboard({ logout }) {
  const [customers, setCustomers] = useState({ data: [], total: 0, page: 1, total_pages: 0, limit: 6 })
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('name')
  const [detail, setDetail] = useState(null)
  const [add, setAdd] = useState(false)
  const load = (page = 1) => api(`/customers?page=${page}&limit=6&phone=${encodeURIComponent(query)}&sort_by=${sort}`).then(setCustomers).catch(() => {})
  useEffect(() => { load() }, [query, sort])
  return <main className="workspace owner-workspace"><nav><b className="brand"><i>TL</i> Tiffin Ledger</b><button className="text-button" onClick={logout}>Log out</button></nav><div className="content"><small>SERVICE CONTROL / {monthNow.toUpperCase()}</small><h1>Good morning, keep lunch moving.</h1><button className="primary" onClick={() => setAdd(true)}>+ Add customer</button><div className="stats"><div>Total customers<strong>{customers.total}</strong></div><div>Active today<strong className="green">{customers.data.filter(item => item.status === 'ACTIVE').length}</strong></div><div>Paused today<strong className="amber">{customers.data.filter(item => item.status === 'PAUSED').length}</strong></div></div><header className="toolbar"><h2>Customers</h2><input placeholder="Search phone..." value={query} onChange={event => setQuery(event.target.value)} /><select value={sort} onChange={event => setSort(event.target.value)}><option value="name">Sort: name</option><option value="phone">Sort: phone</option><option value="plan_price">Sort: plan price</option></select></header><div className="customer-list">{customers.data.map(item => <button key={item.id} onClick={() => setDetail(item)}><b>{item.name}</b><span>{item.phone}</span><span>{money(item.plan_price)}</span><mark className={item.status.toLowerCase()}>{item.status}</mark>→</button>)}</div><footer>Showing {customers.total ? `${(customers.page - 1) * customers.limit + 1}–${Math.min(customers.page * customers.limit, customers.total)} of ${customers.total}` : 'no customers yet'} <span><button disabled={customers.page <= 1} onClick={() => load(customers.page - 1)}>←</button><button disabled={customers.page >= customers.total_pages} onClick={() => load(customers.page + 1)}>→</button></span></footer></div>{detail && <OwnerModal customer={detail} close={() => setDetail(null)} refresh={() => { setDetail(null); load() }} />}{add && <AddCustomer close={() => setAdd(false)} created={() => { setAdd(false); load() }} />}</main>
}

function OwnerModal({ customer, close, refresh }) {
  const [pauses, setPauses] = useState([])
  const [form, setForm] = useState({ start_date: '', end_date: '', reason: '' })
  const [error, setError] = useState('')
  useEffect(() => { api(`/customers/${customer.id}/pauses`).then(setPauses) }, [customer.id])
  const pause = async event => { event.preventDefault(); try { await api(`/customers/${customer.id}/pause`, { method: 'POST', body: JSON.stringify(form) }); setPauses(await api(`/customers/${customer.id}/pauses`)); setForm({ start_date: '', end_date: '', reason: '' }) } catch (caught) { setError(caught.message) } }
  const resume = async () => { try { await api(`/customers/${customer.id}/resume`, { method: 'POST' }); refresh() } catch (caught) { setError(caught.message) } }
  return <div className="shade"><div className="modal"><button className="close" onClick={close}>×</button><small>CUSTOMER RECORD</small><h2>{customer.name}</h2><p>{customer.phone} · {customer.address || 'No address saved'}</p><section><h3>Pause service</h3><form onSubmit={pause}><input required type="date" value={form.start_date} onChange={event => setForm({ ...form, start_date: event.target.value })} /><input required type="date" value={form.end_date} onChange={event => setForm({ ...form, end_date: event.target.value })} /><input placeholder="Reason (optional)" value={form.reason} onChange={event => setForm({ ...form, reason: event.target.value })} /><button className="primary">Pause dates</button></form><button className="outline-button" onClick={resume}>Resume service</button><h3>Pause history</h3>{pauses.map(item => <p className="pause-row" key={item.id}>{item.start_date} to {item.end_date}{item.reason ? ` · ${item.reason}` : ''}</p>)}</section>{error && <em>{error}</em>}</div></div>
}

function AddCustomer({ close, created }) {
  const [form, setForm] = useState({ name: '', phone: '', address: '', plan_price: '', subscription_start_date: today }); const [error, setError] = useState('')
  const submit = async event => { event.preventDefault(); try { await api('/customers', { method: 'POST', body: JSON.stringify({ ...form, plan_price: Number(form.plan_price) }) }); created() } catch (caught) { setError(caught.message) } }
  return <div className="shade"><div className="modal"><button className="close" onClick={close}>×</button><small>NEW SUBSCRIPTION</small><h2>Add a customer</h2><form onSubmit={submit}>{['name', 'phone', 'address'].map(field => <input key={field} required={field !== 'address'} placeholder={field} value={form[field]} onChange={event => setForm({ ...form, [field]: event.target.value })} />)}<input required type="number" placeholder="monthly plan (₹)" value={form.plan_price} onChange={event => setForm({ ...form, plan_price: event.target.value })} /><input required type="date" value={form.subscription_start_date} onChange={event => setForm({ ...form, subscription_start_date: event.target.value })} />{error && <em>{error}</em>}<button className="primary">Add to ledger →</button></form></div></div>
}

function CustomerDashboard({ logout }) {
  const [data, setData] = useState(null); const [month, setMonth] = useState(monthNow); const [tab, setTab] = useState('dashboard'); const [error, setError] = useState(''); const [profile, setProfile] = useState({ name: '', phone: '', address: '' }); const [pause, setPause] = useState({ start_date: today, end_date: today, reason: '' })
  const load = () => api(`/customers/me/dashboard?month=${month}`).then(result => { setData(result); setProfile({ name: result.customer.name, phone: result.customer.phone, address: result.customer.address || '' }) }).catch(caught => setError(caught.message))
  useEffect(() => { load() }, [month])
  if (!data) return <main className="workspace"><div className="content"><p>{error || 'Loading your subscription...'}</p></div></main>
  const submitPause = async event => { event.preventDefault(); if (!window.confirm(`Pause service from ${pause.start_date} to ${pause.end_date}?`)) return; try { await api('/customers/me/pause', { method: 'POST', body: JSON.stringify(pause) }); setTab('subscription'); load() } catch (caught) { setError(caught.message) } }
  const resume = async () => { if (!window.confirm('Resume service today?')) return; try { await api('/customers/me/resume', { method: 'POST' }); load() } catch (caught) { setError(caught.message) } }
  const saveProfile = async event => { event.preventDefault(); try { await api('/customers/me', { method: 'PATCH', body: JSON.stringify(profile) }); load() } catch (caught) { setError(caught.message) } }
  const tabs = [['dashboard', 'Dashboard'], ['subscription', 'My subscription'], ['billing', 'Billing'], ['delivery', 'Delivery history'], ['profile', 'Profile']]
  return <main className="workspace customer-workspace"><nav><b className="brand"><i>TL</i> Tiffin Ledger</b><button className="text-button" onClick={logout}>Log out</button></nav><div className="content"><div className="customer-nav">{tabs.map(([key, label]) => <button className={tab === key ? 'selected' : ''} key={key} onClick={() => setTab(key)}>{label}</button>)}<button className="pause-nav" onClick={() => setTab('pause')}>Pause / resume</button></div><small>YOUR TIFFIN PLAN / {month}</small><h1>Good morning, {data.customer.name.split(' ')[0]}.</h1>{error && <em>{error}</em>}{tab === 'dashboard' && <DashboardHome data={data} month={month} setMonth={setMonth} />}{tab === 'subscription' && <SubscriptionView data={data} onPause={() => setTab('pause')} onResume={resume} />}{tab === 'pause' && <PauseView data={data} form={pause} setForm={setPause} submit={submitPause} resume={resume} />}{tab === 'billing' && <BillingView bill={data.bill} month={month} setMonth={setMonth} />}{tab === 'delivery' && <DeliveryView data={data} />}{tab === 'profile' && <ProfileView profile={profile} setProfile={setProfile} save={saveProfile} />}</div></main>
}

function DashboardHome({ data, month, setMonth }) { return <><div className="status-banner"><div><small>CURRENT STATUS</small><strong className={data.customer.status.toLowerCase()}>{data.customer.status}</strong></div><div><small>TODAY'S DELIVERY</small><strong>{data.today.status.replace('_', ' ')}</strong><span>{data.today.notification ? data.today.notification.message : 'No notification recorded yet'}</span></div></div><div className="metric-grid"><div><small>PLAN</small><strong>{money(data.subscription?.plan_price || data.customer.plan_price)}</strong><span>{data.subscription ? `${data.subscription.cycle_start} to ${data.subscription.cycle_end}` : 'No active subscription'}</span></div><div><small>DELIVERED DAYS</small><strong>{data.bill.delivered_weekdays}</strong><span>in {month}</span></div><div><small>PAUSED DAYS</small><strong>{data.bill.paused_weekdays}</strong><span>weekdays excluded</span></div><div><small>ESTIMATED BILL</small><strong>{money(data.bill.amount)}</strong><span>{data.bill.total_weekdays} weekdays in period</span></div></div><Calendar days={data.calendar} month={month} setMonth={setMonth} /></> }
function SubscriptionView({ data, onPause, onResume }) { return <section className="panel"><div className="panel-heading"><div><small>MY SUBSCRIPTION</small><h2>{money(data.subscription?.plan_price || data.customer.plan_price)} monthly plan</h2></div><strong className={data.customer.status.toLowerCase()}>{data.customer.status}</strong></div><p>Cycle: {data.subscription ? `${data.subscription.cycle_start} to ${data.subscription.cycle_end}` : 'Not assigned'}</p><div className="assignment-list">{data.subscription?.assignments.map(item => <div key={`${item.subscription_id}-${item.start_date}`}><b>{item.is_current_customer ? data.customer.name : 'Previous assignment'}</b><span>{item.start_date} to {item.end_date}</span></div>)}</div><div className="actions"><button className="primary" onClick={onPause}>Pause service</button><button className="outline-button" onClick={onResume}>Resume today</button></div><h3>Pause history</h3>{data.pauses.map(item => <p className="pause-row" key={item.id}><b>{item.status}</b> {item.start_date} to {item.end_date}{item.reason ? ` · ${item.reason}` : ''}</p>)}</section> }
function PauseView({ data, form, setForm, submit, resume }) { return <section className="panel"><small>PAUSE / RESUME</small><h2>Take time away from the route.</h2><p>Paused weekdays are removed from delivery and your bill. Your pause history stays on your account.</p><form onSubmit={submit} className="pause-form"><label>Pause from<input required type="date" value={form.start_date} onChange={event => setForm({ ...form, start_date: event.target.value })} /></label><label>Pause to<input required type="date" value={form.end_date} onChange={event => setForm({ ...form, end_date: event.target.value })} /></label><label>Reason <span>(optional)</span><input value={form.reason} onChange={event => setForm({ ...form, reason: event.target.value })} placeholder="Travel, holiday..." /></label><button className="primary">Confirm pause</button></form><button className="outline-button" onClick={resume}>Resume service today</button><h3>History</h3>{data.pauses.map(item => <p className="pause-row" key={item.id}>{item.start_date} to {item.end_date} · {item.status}</p>)}</section> }
function BillingView({ bill, month, setMonth }) { return <section className="panel"><div className="panel-heading"><div><small>BILLING PERIOD</small><h2>{money(bill.amount)}</h2></div><input type="month" value={month} onChange={event => setMonth(event.target.value)} /></div><div className="bill-lines"><p>Monthly plan price <b>{money(bill.plan_price)}</b></p><p>Total weekdays <b>{bill.total_weekdays}</b></p><p>Paused weekdays <b>{bill.paused_weekdays}</b></p><p>Delivered weekdays <b>{bill.delivered_weekdays}</b></p></div><p className="formula">{money(bill.plan_price)} ÷ {bill.total_weekdays} × {bill.delivered_weekdays}</p></section> }
function DeliveryView({ data }) { return <section className="panel"><div className="panel-heading"><div><small>DELIVERY HISTORY</small><h2>Weekday service calendar</h2></div><div className="legend"><span className="dot delivered" /> Delivered <span className="dot paused" /> Paused <span className="dot weekend" /> Weekend</div></div><div className="delivery-list">{data.calendar.map(item => <div key={item.date}><b>{item.date}</b><span className={`tag ${item.status.toLowerCase()}`}>{item.status.replace('_', ' ')}</span></div>)}</div></section> }
function ProfileView({ profile, setProfile, save }) { return <section className="panel profile-panel"><small>PROFILE</small><h2>Your account details</h2><form onSubmit={save}><label>Name<input required value={profile.name} onChange={event => setProfile({ ...profile, name: event.target.value })} /></label><label>Phone<input required value={profile.phone} onChange={event => setProfile({ ...profile, phone: event.target.value })} /></label><label>Address<textarea value={profile.address} onChange={event => setProfile({ ...profile, address: event.target.value })} /></label><button className="primary">Save profile</button></form></section> }
function Calendar({ days, month, setMonth }) { return <section className="panel calendar-panel"><div className="panel-heading"><div><small>DELIVERY CALENDAR</small><h2>Days in service</h2></div><input type="month" value={month} onChange={event => setMonth(event.target.value)} /></div><div className="calendar-grid">{days.map(item => <div key={item.date} className={`calendar-day ${item.status.toLowerCase()}`}><b>{item.date.slice(-2)}</b><span>{item.status.replace('_', ' ')}</span></div>)}</div></section> }

export default function App() {
  const [screen, setScreen] = useState(localStorage.getItem('tiffin_token') ? (localStorage.getItem('tiffin_role') === 'CUSTOMER' ? 'customer' : 'owner') : 'landing')
  const [mode, setMode] = useState('login'); const [customerAuth, setCustomerAuth] = useState(false)
  const choose = next => { setCustomerAuth(next.startsWith('customer')); setMode(next.includes('register') ? 'register' : 'login'); setScreen('auth') }
  const logout = () => { localStorage.removeItem('tiffin_token'); localStorage.removeItem('tiffin_role'); setScreen('landing') }
  if (screen === 'landing') return <Landing choose={choose} />
  if (screen === 'auth') return <Auth mode={mode} customer={customerAuth} back={() => setScreen('landing')} done={value => value ? choose(value) : setScreen(customerAuth ? 'customer' : 'owner')} />
  return screen === 'customer' ? <CustomerDashboard logout={logout} /> : <OwnerDashboard logout={logout} />
}
