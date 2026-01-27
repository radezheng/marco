import React from 'react'

type TabKey = 'dashboard' | 'cn-sectors'

export type SidebarItem = {
  key: TabKey
  label: string
  icon: React.ReactNode
}

function IconGrid() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <path d="M4 4h7v7H4V4Z" stroke="currentColor" strokeWidth="1.8" />
      <path d="M13 4h7v7h-7V4Z" stroke="currentColor" strokeWidth="1.8" />
      <path d="M4 13h7v7H4v-7Z" stroke="currentColor" strokeWidth="1.8" />
      <path d="M13 13h7v7h-7v-7Z" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

function IconChina() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <path d="M12 2.8l1.6 4.6h4.8l-3.9 2.9 1.5 4.6-4-2.9-4 2.9 1.5-4.6-3.9-2.9h4.8L12 2.8Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M5.2 18.2c2.1 2 4.3 3 6.8 3s4.7-1 6.8-3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

export function Sidebar(props: {
  collapsed: boolean
  setCollapsed: (v: boolean) => void
  active: TabKey
  setActive: (k: TabKey) => void
}) {
  const items: SidebarItem[] = [
    { key: 'dashboard', label: 'Regime Monitor', icon: <IconGrid /> },
    { key: 'cn-sectors', label: 'A股板块', icon: <IconChina /> }
  ]

  return (
    <div className={props.collapsed ? 'sidebar sidebar--collapsed' : 'sidebar'}>
      <div className="sidebar-brand">
        <button
          className="sidebar-collapse sidebar-collapse--top"
          type="button"
          onClick={() => props.setCollapsed(!props.collapsed)}
          aria-label={props.collapsed ? '展开菜单' : '折叠菜单'}
          title={props.collapsed ? '展开菜单' : '折叠菜单'}
        >
          {props.collapsed ? '»' : '«'}
        </button>

        <div className="sidebar-brand-left">
          <div className="sidebar-logo">M</div>
          <div className="sidebar-brand-text">Marco</div>
        </div>
      </div>

      <div className="sidebar-nav">
        {items.map((it) => (
          <button
            key={it.key}
            className={it.key === props.active ? 'sidebar-item sidebar-item--active' : 'sidebar-item'}
            onClick={() => props.setActive(it.key)}
            title={props.collapsed ? it.label : undefined}
            type="button"
          >
            <span className="sidebar-icon">{it.icon}</span>
            <span className="sidebar-label">{it.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export type { TabKey }
