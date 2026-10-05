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

export function MiniChart({ zone, height = 200 }: { zone: Zone; height?: number }) {
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
      crosshair: { mode: 0 },
      handleScroll: false,
      handleScale: false,
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

    const placeOverlay = (barWidth: number, tOb: number) => {
      const x = chart.timeScale().timeToCoordinate(tOb as Time)
      const yTop = series.priceToCoordinate(zone.high)
      const yBot = series.priceToCoordinate(zone.low)
      if (x == null || yTop == null || yBot == null) {
        overlay.style.display = 'none'
        return
      }
      const top = Math.min(yTop, yBot)
      const h = Math.max(Math.abs(yBot - yTop), 6)
      const w = Math.max(barWidth * 6, 28)
      const isBuy = zone.direction === 'bull'
      overlay.style.display = 'flex'
      overlay.style.left = `${x - 2}px`
      overlay.style.top = `${top}px`
      overlay.style.width = `${w}px`
      overlay.style.height = `${h}px`
      overlay.style.background = isBuy ? 'rgba(34,197,94,0.22)' : 'rgba(239,68,68,0.22)'
      overlay.style.border = isBuy
        ? '1px solid rgba(34,197,94,0.85)'
        : '1px solid rgba(239,68,68,0.85)'
      overlay.dataset.label = isBuy ? 'ZONE ACHAT' : 'ZONE VENTE'
      overlay.style.color = isBuy ? '#86efac' : '#fca5a5'
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
        // Estimate bar width from neighboring points
        let barWidth = 8
        if (candles.length >= 2) {
          const x0 = chart.timeScale().timeToCoordinate(candles[0].time as Time)
          const x1 = chart.timeScale().timeToCoordinate(candles[1].time as Time)
          if (x0 != null && x1 != null) barWidth = Math.abs(x1 - x0)
        }

        // Focus view around OB
        const idx = candles.findIndex((c) => c.time >= tOb)
        if (idx >= 0) {
          const from = Math.max(0, idx - 40)
          const to = Math.min(candles.length - 1, idx + 40)
          chart.timeScale().setVisibleLogicalRange({ from, to })
        }

        const redraw = () => placeOverlay(barWidth, tOb)
        redraw()
        chart.timeScale().subscribeVisibleLogicalRangeChange(redraw)
        // entry / SL lines
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
  }, [zone.id, zone.symbol, zone.tf, zone.high, zone.low, zone.direction, zone.ts_ob, zone.entry, zone.sl, height])

  const label = zone.direction === 'bull' ? 'ZONE ACHAT' : 'ZONE VENTE'
  const labelColor = zone.direction === 'bull' ? 'text-emerald-300' : 'text-red-300'

  return (
    <div ref={wrapRef} className="relative w-full overflow-hidden rounded-md bg-[#0c0c0e]">
      <div ref={chartRef} className="w-full" style={{ height }} />
      <div
        ref={overlayRef}
        className={`pointer-events-none absolute flex items-start justify-center overflow-hidden rounded-sm ${labelColor}`}
        style={{ display: 'none', fontSize: 9, fontWeight: 700, letterSpacing: '0.04em' }}
      >
        <span className="mt-0.5 px-0.5 leading-none drop-shadow">{label}</span>
      </div>
    </div>
  )
}
