import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const BASE = '/api/chart-auth'

type Json = Record<string, unknown>

const ROLES = [
  { code: 'ROLE-ADMIN', name: '数据主管' },
  { code: 'ROLE-FIN', name: '财务分析师' },
  { code: 'ROLE-OPS', name: '运营分析师' },
  { code: 'ROLE-REVIEWER', name: '外部评审专家' },
]
const DIMENSIONS = ['地区', '渠道', '日期']

interface ScopeGrantDraft {
  团队编号: string
  角色编号: string | null
  允许维度: string[]
  权限级别: string
}

const DEFAULT_GRANTS: ScopeGrantDraft[] = [
  { 团队编号: 'TEAM-ROOT', 角色编号: 'ROLE-ADMIN', 允许维度: [...DIMENSIONS], 权限级别: 'editor' },
  { 团队编号: 'TEAM-FIN', 角色编号: null, 允许维度: ['地区', '日期'], 权限级别: 'viewer' },
  { 团队编号: 'TEAM-OPS', 角色编号: null, 允许维度: ['渠道', '日期'], 权限级别: 'viewer' },
]

function toggleDimension(draft: ScopeGrantDraft[], index: number, dim: string) {
  return draft.map((item, i) => {
    if (i !== index) return item
    const exists = item.允许维度.includes(dim)
    return {
      ...item,
      允许维度: exists ? item.允许维度.filter((d) => d !== dim) : [...item.允许维度, dim],
    }
  })
}

export default function ChartAuthView() {
  const [master, setMaster] = useState<Json | null>(null)
  const [manifest, setManifest] = useState<Json | null>(null)
  const [tasks, setTasks] = useState<Json[]>([])
  const [copies, setCopies] = useState<Json[]>([])
  const [panelStatus, setPanelStatus] = useState<Json | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [grants, setGrants] = useState<ScopeGrantDraft[]>(DEFAULT_GRANTS)
  const [queryRole, setQueryRole] = useState('ROLE-FIN')
  const [queryDims, setQueryDims] = useState<string[]>(['地区'])
  const [queryResult, setQueryResult] = useState<Json | null>(null)
  const [filterRole, setFilterRole] = useState('ROLE-FIN')
  const [filterInfo, setFilterInfo] = useState<Json | null>(null)

  const loadAll = useCallback(async () => {
    const [m, mf, ts, cp, ps] = await Promise.all([
      request(`${BASE}/master`).then((r) => r.json()),
      request(`${BASE}/manifest`).then((r) => r.json()),
      request(`${BASE}/tasks`).then((r) => r.json()),
      request(`${BASE}/review-copies`).then((r) => r.json()),
      request(`${BASE}/panels/status`).then((r) => r.json()),
    ])
    setMaster(m)
    setManifest(mf)
    setTasks(ts)
    setCopies(cp)
    setPanelStatus(ps)
  }, [])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const loadFilter = useCallback(async (role: string) => {
    const data = await request(`${BASE}/filter-dimensions?role=${role}`).then((r) => r.json())
    setFilterInfo(data)
  }, [])

  useEffect(() => {
    void loadFilter(filterRole)
  }, [filterRole, loadFilter])

  async function callApi(path: string, init?: RequestInit, successText?: string) {
    setError('')
    setMessage('')
    try {
      const response = await request(path, init)
      const payload = await response.json()
      if (!response.ok) {
        setError(payload.detail ?? '请求被拒绝')
        return payload
      }
      if (successText) setMessage(successText)
      await loadAll()
      return payload
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败')
    }
  }

  function submitScope() {
    void callApi(
      `${BASE}/scope`,
      {
        method: 'PUT',
        body: JSON.stringify({ operator_role: 'ROLE-ADMIN', grants, remark: '前端调整可见范围' }),
      },
      '可见范围已更新，并为看板面板与筛选器生成核对任务',
    )
  }

  function runQuery() {
    setError('')
    setQueryResult(null)
    void request(`${BASE}/query`, {
      method: 'POST',
      body: JSON.stringify({ role: queryRole, dimensions: queryDims }),
    })
      .then(async (response) => {
        const payload = await response.json()
        if (!response.ok) {
          setError(payload.detail)
          return
        }
        setQueryResult(payload)
      })
      .catch((e) => setError(e instanceof Error ? e.message : '查询失败'))
  }

  function createCopy() {
    void callApi(
      `${BASE}/review-copies`,
      {
        method: 'POST',
        body: JSON.stringify({
          operator_role: 'ROLE-ADMIN',
          target_role: 'ROLE-REVIEWER',
          freeze_dimensions: ['地区', '日期'],
        }),
      },
      '只读评审副本已生成，维度与范围版本已冻结',
    )
  }

  const masterRow = master?.主记录 as Json | undefined
  const versions = (master?.版本流水 as Json[]) ?? []
  const chartSection = manifest?.['图表配置'] as Json | undefined
  const panelSection = manifest?.['数据看板面板'] as Json | undefined
  const filterSection = manifest?.['全局筛选器'] as Json | undefined

  return (
    <section className="page" data-module="chart-auth">
      <header className="page-head">
        <div>
          <h2>图表配置角色授权（CFG-0005）</h2>
          <p className="page-desc">
            主对象为图表配置：可见范围、坐标轴绑定与配置版本以主记录为准；看板只引用图表，授权按团队归属逐角色控制。
          </p>
        </div>
      </header>

      {message && <div className="banner ok">{message}</div>}
      {error && <div className="banner error">{error}</div>}

      {/* 一、图表配置主记录 */}
      <h3 className="block-title">一、图表配置主记录（三要素先确定）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>图表编号</th><th>图表名称</th><th>数据集</th><th>横轴（绑定）</th>
            <th>纵轴（绑定）</th><th>配置版本</th><th>范围版本</th><th>授权状态</th><th>只读</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{String(masterRow?.['图表编号'])}</td>
            <td>{String(masterRow?.['图表名称'])}</td>
            <td>{String(masterRow?.['数据集编号'])}</td>
            <td>{String(masterRow?.['横轴字段'])}</td>
            <td>{String(masterRow?.['纵轴字段'])}</td>
            <td>{String(masterRow?.['图表配置版本'])}</td>
            <td>{String(masterRow?.['可见范围版本'])}</td>
            <td><span className={`tag ${masterRow?.['授权状态'] === '已核对' ? 'tag-ok' : 'tag-warn'}`}>{String(masterRow?.['授权状态'])}</span></td>
            <td>{masterRow?.['只读'] ? '是' : '否'}</td>
          </tr>
        </tbody>
      </table>
      <details className="version-box">
        <summary>配置版本流水（{versions.length} 条，范围调整与绑定调整分别留痕）</summary>
        <table className="data-table">
          <thead><tr><th>版本号</th><th>范围版本</th><th>变更类型</th><th>说明</th><th>时间</th></tr></thead>
          <tbody>
            {versions.map((v) => (
              <tr key={String(v.id)}>
                <td>{String(v['版本号'])}</td><td>{String(v['范围版本'])}</td>
                <td>{String(v['变更类型'])}</td><td>{String(v['说明'])}</td><td>{String(v['创建时间'])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      {/* 二、三对象授权清单 */}
      <h3 className="block-title">二、CFG-0005 / DASH-0002 / FILT-0003 授权清单（分对象列出，非全局开关）</h3>
      <div className="grid-3">
        {[
          { key: '图表配置', section: chartSection, code: 'CFG-0005' },
          { key: '数据看板面板', section: panelSection, code: 'DASH-0002' },
          { key: '全局筛选器', section: filterSection, code: 'FILT-0003' },
        ].map(({ key, section, code }) => {
          const decisions = (section?.['角色裁决'] as Json[]) ?? []
          const authStatus = section?.['授权状态']
          return (
            <article key={key} className="auth-card">
              <header>
                <strong>{key} · {code}</strong>
                {authStatus ? <span className="tag tag-warn">{String(authStatus)}</span> : null}
              </header>
              <p className="muted">可见团队：{((section?.['可见团队'] as Json[]) ?? []).map((t) => String(t['团队名称'])).join('、') || '无'}</p>
              <table className="data-table inner">
                <thead><tr><th>角色</th><th>级别</th><th>允许/暴露维度</th><th>继承来源</th></tr></thead>
                <tbody>
                  {decisions.map((d) => (
                    <tr key={String(d['角色编号'])}>
                      <td>{String(d['角色编号'])}</td>
                      <td>{String(d['权限级别'])}</td>
                      <td>{((d['实际暴露维度'] as string[]) ?? (d['允许维度'] as string[]) ?? []).join('、')}</td>
                      <td>{String(d['裁决说明'])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </article>
          )
        })}
      </div>

      {/* 三、越权拦截演示 */}
      <h3 className="block-title">三、越权筛选入口拦截（未授权维度必须拒绝，图表结果不被改变）</h3>
      <div className="toolbar">
        <label>角色
          <select value={queryRole} onChange={(e) => setQueryRole(e.target.value)}>
            {ROLES.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
          </select>
        </label>
        <div className="dim-picker">
          {DIMENSIONS.map((dim) => (
            <label key={dim} className="check">
              <input
                type="checkbox"
                checked={queryDims.includes(dim)}
                onChange={() =>
                  setQueryDims((prev) => prev.includes(dim) ? prev.filter((d) => d !== dim) : [...prev, dim])
                }
              />
              {dim}
            </label>
          ))}
        </div>
        <button className="btn primary" type="button" onClick={runQuery}>查询图表数据</button>
      </div>
      {queryResult && (
        <table className="data-table">
          <thead>
            <tr>
              {(queryResult['数据'] as Json[])[0] && Object.keys((queryResult['数据'] as Json[])[0]).map((k) => <th key={k}>{k}</th>)}
            </tr>
          </thead>
          <tbody>
            {(queryResult['数据'] as Json[]).map((row, i) => (
              <tr key={i}>{Object.values(row).map((v, j) => <td key={j}>{String(v)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 className="block-title">四、全局筛选器按角色暴露联动维度</h3>
      <div className="toolbar">
        <label>角色
          <select value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
            {ROLES.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
          </select>
        </label>
        {filterInfo && (
          <div className="filter-expose">
            <span>实际暴露：<b>{((filterInfo['实际暴露维度'] as string[]) ?? []).join('、') || '无'}</b></span>
            <span className="muted">被隐藏：{((filterInfo['被隐藏维度'] as string[]) ?? []).join('、') || '无'}</span>
          </div>
        )}
      </div>

      {/* 五、可见范围调整 */}
      <h3 className="block-title">五、按角色调整可见范围（保存即生成相邻模块核对任务）</h3>
      <table className="data-table">
        <thead><tr><th>团队</th><th>角色（空=团队默认继承）</th><th>允许维度</th><th>级别</th><th></th></tr></thead>
        <tbody>
          {grants.map((grant, index) => (
            <tr key={`${grant.团队编号}-${grant.角色编号 ?? 'default'}`}>
              <td>{grant.团队编号}</td>
              <td>{grant.角色编号 ?? '团队默认'}</td>
              <td>
                {DIMENSIONS.map((dim) => (
                  <label key={dim} className="check">
                    <input
                      type="checkbox"
                      checked={grant.允许维度.includes(dim)}
                      onChange={() => setGrants((prev) => toggleDimension(prev, index, dim))}
                    />
                    {dim}
                  </label>
                ))}
              </td>
              <td>{grant.权限级别}</td>
              <td>
                <button
                  className="link"
                  type="button"
                  onClick={() => setGrants((prev) => prev.filter((_, i) => i !== index))}
                >移除</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="toolbar">
        <button className="btn primary" type="button" onClick={submitScope}>保存可见范围（仅数据主管可执行）</button>
        <button className="btn ghost" type="button" onClick={() => setGrants(DEFAULT_GRANTS)}>重置为初始授权</button>
      </div>

      {/* 六、核对任务与看板状态 */}
      <h3 className="block-title">六、授权核对任务（结果同步回图表与看板）</h3>
      <div className="toolbar">
        {panelStatus && (
          <span className="muted">
            图表主记录：{String(panelStatus['图表主记录授权状态'])} ｜
            面板 DASH-0002：{String((panelStatus['看板面板'] as Json[])[0]?.['授权状态'])} ｜
            筛选器 FILT-0003：{String((panelStatus['全局筛选器'] as Json[])[0]?.['授权状态'])}
          </span>
        )}
      </div>
      <table className="data-table">
        <thead><tr><th>任务编号</th><th>对象</th><th>范围版本</th><th>状态</th><th>结论</th><th>操作</th></tr></thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={String(task.id)}>
              <td>{String(task['任务编号'])}</td>
              <td>{String(task['对象类型'])} {String(task['对象编号'])}</td>
              <td>{String(task['范围版本'])}</td>
              <td><span className={`tag ${task['状态'] === '已完成' ? 'tag-ok' : 'tag-warn'}`}>{String(task['状态'])}</span></td>
              <td>{String(task['核对结论'] || '—')}</td>
              <td>
                {task['状态'] === '待核对' && (
                  <button
                    className="link"
                    type="button"
                    onClick={() =>
                      callApi(
                        `${BASE}/tasks/${String(task.id)}/complete`,
                        {
                          method: 'POST',
                          body: JSON.stringify({
                            operator_role: 'ROLE-ADMIN',
                            conclusion: `${String(task['对象编号'])} 可见团队与范围一致，核对通过`,
                          }),
                        },
                        '核对结果已回写，图表与看板授权状态已刷新',
                      )
                    }
                  >回写核对结果</button>
                )}
              </td>
            </tr>
          ))}
          {tasks.length === 0 && <tr><td className="empty-state" colSpan={6}>暂无核对任务</td></tr>}
        </tbody>
      </table>

      {/* 七、只读评审副本 */}
      <h3 className="block-title">七、只读评审副本（冻结维度，收紧不回溯、新增维度不可见）</h3>
      <div className="toolbar">
        <button className="btn primary" type="button" onClick={createCopy}>为外部评审生成只读副本（冻结地区+日期）</button>
      </div>
      <table className="data-table">
        <thead><tr><th>副本编号</th><th>目标角色</th><th>冻结配置版本</th><th>冻结范围版本</th><th>冻结维度</th><th>只读</th><th>状态</th></tr></thead>
        <tbody>
          {copies.map((copy) => (
            <tr key={String(copy.id)}>
              <td>{String(copy['副本编号'])}</td>
              <td>{String(copy['目标角色编号'])}</td>
              <td>{String(copy['冻结配置版本'])}</td>
              <td>{String(copy['冻结范围版本'])}</td>
              <td>{((copy['冻结维度'] as string[]) ?? []).join('、')}</td>
              <td>{copy['只读'] ? '是（受控维度禁改）' : '否'}</td>
              <td>{String(copy['状态'])}</td>
            </tr>
          ))}
          {copies.length === 0 && <tr><td className="empty-state" colSpan={7}>暂无评审副本</td></tr>}
        </tbody>
      </table>
    </section>
  )
}
