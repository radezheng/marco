import React from 'react'

export function HoverHelp(props: {
  title: string
  body: string
  delayMs?: number
  children: React.ReactNode
}) {
  const delayMs = props.delayMs ?? 2000

  const [visible, setVisible] = React.useState(false)
  const [pos, setPos] = React.useState<{ x: number; y: number }>({ x: 0, y: 0 })

  const timerRef = React.useRef<number | null>(null)
  const lastPosRef = React.useRef<{ x: number; y: number }>({ x: 0, y: 0 })

  function clearTimer() {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  React.useEffect(() => {
    return () => {
      clearTimer()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function clampPosition(p: { x: number; y: number }) {
    const margin = 12
    const tipW = 380
    const tipH = 220

    const maxX = Math.max(margin, window.innerWidth - tipW - margin)
    const maxY = Math.max(margin, window.innerHeight - tipH - margin)

    return {
      x: Math.min(Math.max(p.x, margin), maxX),
      y: Math.min(Math.max(p.y, margin), maxY)
    }
  }

  function onEnter(e: React.MouseEvent) {
    lastPosRef.current = { x: e.clientX + 14, y: e.clientY + 14 }
    clearTimer()
    timerRef.current = window.setTimeout(() => {
      setPos(clampPosition(lastPosRef.current))
      setVisible(true)
    }, delayMs)
  }

  function onMove(e: React.MouseEvent) {
    lastPosRef.current = { x: e.clientX + 14, y: e.clientY + 14 }
    if (visible) setPos(clampPosition(lastPosRef.current))
  }

  function onLeave() {
    clearTimer()
    setVisible(false)
  }

  return (
    <div className="hover-help-wrap" onMouseEnter={onEnter} onMouseMove={onMove} onMouseLeave={onLeave}>
      {props.children}
      {visible ? (
        <div className="hover-help-tip" style={{ left: pos.x, top: pos.y }}>
          <div className="hover-help-title">{props.title}</div>
          <div className="hover-help-body">{props.body}</div>
        </div>
      ) : null}
    </div>
  )
}
