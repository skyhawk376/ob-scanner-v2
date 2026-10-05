import {
  CandlestickSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import { fetchCandles } from '../lib/api'
import type { Timeframe, Zone } from '../lib/types'

function toUnix(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000)
}

/** Nearest candle unix time to target (for reliable timeToCoordinate). */
function nearestTime(candles: { time: number }[], target: number): number {
  if (!candles.length) return target
  let best = candles[0].time
  let bestDist = Math.abs(best - target)
  for (const c of candles) {
    const d = Math.abs(c.time - target)
    if (d < bestDist) {
      best = c.time
      bestDist = d
    }
  }
  return best
}

export function MiniChart({
  zone,
  height = 200,
  interactive = false,
}: {
  zone: Zone
  height?: number
  interactive?: boolean
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<{ chart: IChartApi; series: ISeriesApi<'Candlestick'> } | null>(null)

  useEffect(() => {
    const el = chartRef.current
    const overlay = overlayRef.current
    if (!el || !overlay) return

    let cancelled = false
    const chart = createChart(el, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#0c0c0e' },
        textColor: '#71717a',
        fontSize: 10,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: '#18181b' },
        horzLines: { color: '#18181b' },
      },
      rightPriceScale: {
        borderColor: '#27272a',
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderColor: '#27272a',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: interactive ? 1 : 0 },
      handleScroll: interactive,
      handleScale: interactive,
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    apiRef.current = { chart, series }

    const isBuy = zone.direction === 'bull'

    const styleOverlay = () => {
      overlay.style.background = isBuy ? 'rgba(34,197,94,0.30)' : 'rgba(239,68,68,0.30)'
      overlay.style.border = isBuy
        ? '1.5px solid rgba(34,197,94,0.95)'
        : '1.5px solid rgba(239,68,68,0.95)'
      overlay.style.boxShadow = isBuy
        ? 'inset 0 0 14px rgba(34,197,94,0.18)'
        : 'inset 0 0 14px rgba(239,68,68,0.18)'
      overlay.style.color = isBuy ? '#86efac' : '#fca5a5'
    }

    const placeFullWidthBand = (top: number, h: number) => {
      overlay.style.display = 'flex'
      overlay.style.left = '0'
      overlay.style.right = '0'
      overlay.style.top = `${top}px`
      overlay.style.width = '100%'
      overlay.style.height = `${h}px`
      styleOverlay()
    }

    const placeOverlay = (barWidth: number, tAnchor: number) => {
      const yTop = series.priceToCoordinate(zone.high)
      const yBot = series.priceToCoordinate(zone.low)
      if (yTop == null || yBot == null) {
        overlay.style.display = 'none'
        return
      }
      const top = Math.min(yTop, yBot)
      const h = Math.max(Math.abs(yBot - yTop), 10)
      const chartW = wrapRef.current?.clientWidth ?? el.clientWidth
      const x = chart.timeScale().timeToCoordinate(tAnchor as Time)

      // Prefer timed rectangle; fall back to full-width band if time coord missing/off-screen
      if (x != null && Number.isFinite(x) && chartW > 0 && x >= -20 && x <= chartW + 20) {
        const w = Math.max(barWidth * 6, 40)
        overlay.style.display = 'flex'
        overlay.style.left = `${Math.max(0, Math.min(chartW - w, x - 2))}px`
        overlay.style.right = 'auto'
        overlay.style.top = `${top}px`
        overlay.style.width = `${w}px`
        overlay.style.height = `${h}px`
        styleOverlay()
      } else {
        placeFullWidthBand(top, h)
      }
    }

    const ro = new ResizeObserver(() => {
      if (wrapRef.current) {
        chart.applyOptions({ width: wrapRef.current.clientWidth })
      }
    })
    if (wrapRef.current) ro.observe(wrapRef.current)

    ;(async () => {
      try {
        const candles = await fetchCandles(zone.symbol, zone.tf as Timeframe, 160)
        if (cancelled) return
        if (!candles.length) {
          overlay.style.display = 'none'
          return
        }
        series.setData(
          candles.map((c) => ({
            time: c.time as UTCTimestamp,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          })),
        )
        chart.timeScale().fitContent()

        const tOb = toUnix(zone.ts_ob)
        const tAnchor = nearestTime(candles, tOb)

        let barWidth = 8
        if (candles.length >= 2) {
          const x0 = chart.timeScale().timeToCoordinate(candles[0].time as Time)
          const x1 = chart.timeScale().timeToCoordinate(candles[1].time as Time)
          if (x0 != null && x1 != null) barWidth = Math.abs(x1 - x0)
        }

        const idx = candles.findIndex((c) => c.time >= tAnchor)
        if (idx >= 0) {
          const from = Math.max(0, idx - 40)
          const to = Math.min(candles.length - 1, idx + 40)
          chart.timeScale().setVisibleLogicalRange({ from, to })
        }

        const redraw = () => placeOverlay(barWidth, tAnchor)
        // Two frames: logical range + layout settle before measuring coords
        requestAnimationFrame(() => requestAnimationFrame(redraw))
        chart.timeScale().subscribeVisibleLogicalRangeChange(redraw)

        series.createPriceLine({
          price: zone.entry,
          color: '#60a5fa',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: false,
          title: '',
        })
        series.createPriceLine({
          price: zone.sl,
          color: '#f97316',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: false,
          title: '',
        })
      } catch {
        if (!cancelled) overlay.style.display = 'none'
      }
    })()

    return () => {
      cancelled = true
      ro.disconnect()
      chart.remove()
      apiRef.current = null
    }
  }, [
    zone.id,
    zone.symbol,
    zone.tf,
    zone.high,
    zone.low,
    zone.direction,
    zone.ts_ob,
    zone.entry,
    zone.sl,
    height,
    interactive,
  ])

  const label = zone.direction === 'bull' ? 'ZONE ACHAT' : 'ZONE VENTE'
  const labelColor = zone.direction === 'bull' ? 'text-emerald-300' : 'text-red-300'

  return (
    <div
      ref={wrapRef}
      className={`relative w-full overflow-hidden rounded-md bg-[#0c0c0e] ${interactive ? '' : 'pointer-events-none'}`}
    >
      <div ref={chartRef} className="w-full" style={{ height }} />
      <div
        ref={overlayRef}
        className={`pointer-events-none absolute z-[1] flex items-start justify-center overflow-hidden rounded-sm ${labelColor}`}
        style={{ display: 'none', fontSize: 9, fontWeight: 700, letterSpacing: '0.04em' }}
      >
        <span className="mt-0.5 px-0.5 leading-none drop-shadow">{label}</span>
      </div>
    </div>
  )
}
