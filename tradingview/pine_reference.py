"""Port Python 1:1 de la logique de `OB_Scanner_FiltreB.pine` (référence de parité).

Ce module ne réutilise PAS le moteur du scanner : il rejoue, barre par barre et de
façon causale, exactement l'algorithme écrit en Pine (mêmes boucles, mêmes états),
pour pouvoir le comparer au moteur de prod (`backend/app/engine/detect.py` +
`backend/app/core/lifecycle.py`) sur les bougies du cache.

Algorithme (identique au Pine) — à chaque barre clôturée b :
  1. pivot fractal strict confirmé en i = b - N (N = pivot_n) ;
  2. cycle de vie des zones existantes sur la barre b (expirée barres / distance
     > 8 ATR, puis 1er contact = touchée, puis SL (échec) / +2R (réaction)) ;
  3. détection du BOS sur la barre j = b - (N - 1) : à ce moment, tous les pivots
     d'indice < j que le scanner connaîtra sont confirmés → mêmes BOS que le scanner
     (le scanner « voit » des pivots non encore confirmés au moment du BOS) ;
     OB = dernière bougie opposée à/avant le creux (sommet) de la jambe ;
  4. étoiles : ★1 FVG (OB vs OB+2), ★2 tendance (2 derniers PH/PL), ★3 Fib 0.5 strict
     (swing figé + extrême courant depuis le BOS → mis à jour à chaque barre tant que
     la zone est vierge), ★4 liquidité (aucun pivot non pris / égaux dans 1 ATR derrière
     l'OB), ★5 session Londres 08:00-11:30 / NY 14:30-17:30 Europe/Paris (OB, OB+1 ou
     creux de jambe) ; H4/D/W : ★5 évaluée au toucher.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

PARIS = ZoneInfo("Europe/Paris")

ST_ACTIVE, ST_TOUCHED, ST_REACTION, ST_FAIL, ST_EXPIRED = 0, 1, 2, 3, 4
STATUS_NAME = {0: "active", 1: "touchee", 2: "reaction", 3: "echec", 4: "expiree"}

# Paramètres du scanner (backend/app/engine/params.py + core/lifecycle.py)
SL_BUF_ATR = 0.05
ENTRY_MID_ATR = 1.0
LIQ_BAND_ATR = 1.0
LIQ_EQ_ATR = 0.1
LIQ_EQ_PCT = 0.0005
MAX_DIST_ATR = 8.0
RR = 2.0
ATR_LEN = 14


def tf_params(tf: str) -> dict:
    """Même table que le Pine (auto)."""
    tf = tf.upper()
    pivot_n = 2 if tf in ("D", "W") else 3
    lookback = {"D": 400, "W": 260}.get(tf, 500)
    expiry = {"H4": 150, "D": 120, "W": 52}.get(tf, 200)
    pending = tf in ("H4", "D", "W")
    return dict(pivot_n=pivot_n, lookback=lookback, expiry=expiry, pending=pending)


def in_session(ts_sec: int) -> bool:
    d = datetime.fromtimestamp(ts_sec, timezone.utc).astimezone(PARIS)
    m = d.hour * 60 + d.minute
    return (480 <= m < 690) or (870 <= m < 1050)


def pine_atr(h, l, c, length=ATR_LEN):
    """ta.atr(length) = ta.rma(ta.tr(true), length) (seed = SMA des `length` 1ers TR)."""
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(n, np.nan)
    if n >= length:
        out[length - 1] = tr[:length].mean()
        for i in range(length, n):
            out[i] = (out[i - 1] * (length - 1) + tr[i]) / length
    return out


@dataclass
class PZone:
    bull: bool
    ob: int
    ob_time: int
    top: float
    bot: float
    bos: int
    leg: int
    atr: float
    s1: bool
    s2: bool
    s4: bool
    s5: bool
    pending: bool
    sw_fix: float      # bull: swing low (figé) / bear: swing high (figé)
    sw_run: float      # bull: plus haut depuis le BOS / bear: plus bas depuis le BOS
    h_bos: float       # repli du scanner si swing incohérent
    entry: float
    sl: float
    tp: float
    status: int = ST_ACTIVE
    touch: int = -1
    end: int = -1
    s3_frozen: bool | None = None
    s5_touch: bool = False
    s4_until: int = -1

    def s3(self) -> bool:
        if self.s3_frozen is not None:
            return self.s3_frozen
        if self.bull:
            hi = self.sw_run if self.sw_run >= self.sw_fix else self.h_bos
            fib = self.sw_fix + 0.5 * (hi - self.sw_fix)
            return self.top <= fib
        lo = self.sw_run if self.sw_run <= self.sw_fix else self.h_bos
        fib = lo + 0.5 * (self.sw_fix - lo)
        return self.bot >= fib

    def score(self) -> int:
        s5 = self.s5_touch if self.pending else self.s5
        return int(self.s1) + int(self.s2) + int(self.s3()) + int(self.s4) + int(s5)

    def score_pre(self) -> int:
        """Score tant que la zone était active (= ce que le scanner a listé)."""
        return int(self.s1) + int(self.s2) + int(self.s3()) + int(self.s4) + int(self.s5 and not self.pending)


class PineEngine:
    def __init__(self, o, h, l, c, t, tf: str, **over):
        self.o, self.h, self.l, self.c = (np.asarray(x, float) for x in (o, h, l, c))
        self.t = np.asarray(t, np.int64)  # bar open time, epoch seconds
        p = tf_params(tf)
        p.update(over)
        self.N = p["pivot_n"]
        self.L = p["lookback"]
        self.EXP = p["expiry"]
        self.PENDING = p["pending"]
        self.D = self.N - 1
        self.atr = pine_atr(self.h, self.l, self.c)
        self.ph: list[tuple[int, float]] = []
        self.pl: list[tuple[int, float]] = []
        self.last_bull = math.nan
        self.last_bear = math.nan
        self.zones: list[PZone] = []
        self.b = -1

    # ---------------------------------------------------------------- helpers
    def _pivot(self, i: int):
        N, h, l = self.N, self.h, self.l
        isH = isL = True
        for k in range(1, N + 1):
            if not (h[i] > h[i - k] and h[i] > h[i + k]):
                isH = False
            if not (l[i] < l[i - k] and l[i] < l[i + k]):
                isL = False
        return isH, isL

    def _trend(self) -> int:
        if len(self.ph) < 2 or len(self.pl) < 2:
            return 0
        h1, h2 = self.ph[-2][1], self.ph[-1][1]
        l1, l2 = self.pl[-2][1], self.pl[-1][1]
        if h2 > h1 and l2 > l1:
            return 1
        if h2 < h1 and l2 < l1:
            return -1
        return 0

    def _liq(self, bull: bool, ob: int, top: float, bot: float, atr: float, ws: int) -> int:
        """★4 : renvoie -1 si OK, sinon l'indice jusqu'auquel l'échec tient (max des raisons :
        pivot non pris → son indice ; paire de pivots égaux → indice du plus ancien). Quand la
        fenêtre du scanner (ws + N) dépasse cet indice, ★4 redevient vraie (comme le scanner)."""
        tol = max(LIQ_EQ_ATR * atr, LIQ_EQ_PCT * abs((top + bot) / 2))
        piv = self.pl if bull else self.ph
        b_lo, b_hi = (bot - LIQ_BAND_ATR * atr, bot) if bull else (top, top + LIQ_BAND_ATR * atr)
        until = -1
        eq: list[tuple[int, float]] = []
        for (i, p) in piv:
            if i >= ob:
                break
            if i < ws + self.N or p < b_lo or p > b_hi:
                continue
            ext_lo, ext_hi = math.inf, -math.inf
            for x in range(i + 1, ob):
                ext_lo = min(ext_lo, self.l[x])
                ext_hi = max(ext_hi, self.h[x])
            if bull:
                if not (ext_lo <= p + tol):      # pivot jamais repris → liquidité intacte
                    until = i
                elif not (ext_lo < p - tol):
                    eq.append((i, p))
            else:
                if not (ext_hi >= p - tol):
                    until = i
                elif not (ext_hi > p + tol):
                    eq.append((i, p))
        for a in range(len(eq)):
            for bb in range(a + 1, len(eq)):
                if abs(eq[bb][1] - eq[a][1]) <= tol:
                    until = max(until, eq[a][0])
        return until

    def _new_zone(self, bull: bool, ob: int, j: int, k: int):
        o, h, l, t = self.o, self.h, self.l, self.t
        atr = float(self.atr[j])
        top, bot = float(h[ob]), float(l[ob])
        s1 = bool(h[ob] < l[ob + 2]) if bull else bool(l[ob] > h[ob + 2])
        tr = self._trend()
        s2 = (tr == 1) if bull else (tr == -1)
        sw_fix = float(l[k]) if bull else float(h[k])      # = min(l[k..j]) / max(h[k..j])
        h_bos = float(h[j]) if bull else float(l[j])
        s5 = False
        if not self.PENDING:
            s5 = in_session(t[ob]) or in_session(t[ob + 1]) or in_session(t[k])
        entry = (top + bot) / 2 if (top - bot) > ENTRY_MID_ATR * atr else float(o[ob])
        if bull:
            sl = bot - SL_BUF_ATR * atr
            risk = entry - sl
            tp = entry + RR * risk if risk > 0 else entry
        else:
            sl = top + SL_BUF_ATR * atr
            risk = sl - entry
            tp = entry - RR * risk if risk > 0 else entry
        # ★4 = False ici : calculée seulement si la zone survit (vierge au BOS + FVG)
        return PZone(bull, ob, int(t[ob]), top, bot, j, k, atr, s1, s2, False, s5, self.PENDING,
                     sw_fix, h_bos, h_bos, entry, sl, tp)

    def _life_bar(self, z: PZone, x: int) -> None:
        """Une barre de cycle de vie (mêmes règles/ordre que simulate_lifecycle, entry=mid).

        Avant OB+3 : seul l'extrême du swing (★3) est mis à jour (le scanner l'inclut)."""
        h, l, c = self.h, self.l, self.c
        if x < z.ob + 3:
            if z.status == ST_ACTIVE and x > z.bos:
                z.sw_run = max(z.sw_run, h[x]) if z.bull else min(z.sw_run, l[x])
            return
        if z.status == ST_ACTIVE:
            if x - z.ob > self.EXP:
                z.status, z.end = ST_EXPIRED, x
                return
            if z.atr > 0 and abs((z.top + z.bot) / 2 - c[x]) / z.atr > MAX_DIST_ATR:
                z.status, z.end = ST_EXPIRED, x
                return
            if l[x] <= z.top and h[x] >= z.bot:
                z.s3_frozen = z.s3()          # score figé = dernier scan avant le contact
                z.status, z.touch, z.end = ST_TOUCHED, x, x
                z.s5_touch = in_session(int(self.t[x]))
            else:
                if x > z.bos:  # extrême depuis le BOS
                    z.sw_run = max(z.sw_run, h[x]) if z.bull else min(z.sw_run, l[x])
                return
        if z.status == ST_TOUCHED:
            z.end = x
            if z.bull:
                if l[x] <= z.sl:
                    z.status = ST_FAIL
                elif h[x] >= z.tp:
                    z.status = ST_REACTION
            else:
                if h[x] >= z.sl:
                    z.status = ST_FAIL
                elif l[x] <= z.tp:
                    z.status = ST_REACTION

    def _bos(self, j: int, b: int, ws: int, lvl: list) -> list[PZone]:
        """BOS haussier puis baissier sur la barre j (vue du scanner à la clôture de b).

        `lvl` = [last_bull, last_bear] (modifié en place). Retourne les zones retenues."""
        o, h, l, c = self.o, self.h, self.l, self.c
        out: list[PZone] = []
        if j < ws + 2 * self.N + 2 or not (self.atr[j] > 0):
            return out
        for side, bull in enumerate((True, False)):
            piv = self.ph if bull else self.pl
            if not piv:
                continue
            pi, pp = piv[-1]
            brk = c[j] > pp if bull else c[j] < pp
            if not brk or pp == lvl[side]:
                continue
            k = pi
            for x in range(pi, j + 1):
                if (l[x] < l[k]) if bull else (h[x] > h[k]):
                    k = x
            ob = -1
            for x in range(k, ws - 1, -1):
                if (c[x] < o[x]) if bull else (c[x] > o[x]):
                    ob = x
                    break
            if ob < 0 or ob >= j or ob + 2 > b:
                continue
            lvl[side] = pp
            z = self._new_zone(bull, ob, j, k)
            # rejoue le cycle de vie jusqu'à b : touchée/expirée AVANT ou AU BOS → jamais listée ;
            # après le BOS → listée par le scanner puis touchée/expirée (historique)
            dead = False
            for x in range(min(ob + 3, j + 1), b + 1):
                self._life_bar(z, x)
                if z.status != ST_ACTIVE and x <= j:
                    dead = True
                    break
            if dead or not z.s1:
                continue
            z.s4_until = self._liq(bull, ob, z.top, z.bot, z.atr, ws)
            z.s4 = z.s4_until < 0
            out.append(z)
        return out

    @staticmethod
    def _merge(zones: list[PZone], z: PZone) -> None:
        """Dédoublonnage (même OB, même sens, zone active) : meilleur score, égalité → BOS récent."""
        for i, y in enumerate(zones):
            if y.bull == z.bull and y.ob == z.ob and y.status == ST_ACTIVE:
                if z.score() >= y.score():
                    zones[i] = z
                return
        zones.append(z)

    # ---------------------------------------------------------------- main step
    def step(self) -> None:
        self.b += 1
        b, N, D = self.b, self.N, self.D
        h, l = self.h, self.l
        ws = max(0, b - self.L + 1)  # fenêtre du scanner (lookback barres clôturées)
        # 1. pivots
        if b >= 2 * N:
            i = b - N
            isH, isL = self._pivot(i)
            if isH:
                self.ph.append((i, float(h[i])))
            if isL:
                self.pl.append((i, float(l[i])))
        # pivots hors fenêtre du scanner (il ne détecte les pivots qu'à partir de ws + N)
        while self.ph and self.ph[0][0] < ws + N:
            self.ph.pop(0)
        while self.pl and self.pl[0][0] < ws + N:
            self.pl.pop(0)
        # 2. cycle de vie des zones existantes
        for z in self.zones:
            if z.status in (ST_ACTIVE, ST_TOUCHED):
                self._life_bar(z, b)
            # ★4 : la fenêtre glissante du scanner a fait sortir les pivots bloquants
            if z.status == ST_ACTIVE and not z.s4 and z.s4_until < ws + N:
                z.s4 = True
        # 3. BOS définitif sur j = b - D (tous les pivots d'indice < j sont confirmés)
        lvl = [self.last_bull, self.last_bear]
        for z in self._bos(b - D, b, ws, lvl):
            self._merge(self.zones, z)
        self.last_bull, self.last_bear = lvl

    def provisional(self) -> list[PZone]:
        """Vue « scanner » des D dernières barres (BOS j > b - D, pivots non encore tous
        confirmés) : calculée seulement sur la dernière barre (affichage / alertes), comme le
        scanner qui peut ensuite la retirer. Fusionnée avec les zones définitives."""
        b, ws = self.b, max(0, self.b - self.L + 1)
        lvl = [self.last_bull, self.last_bear]
        prov: list[PZone] = []
        for j in range(b - self.D + 1, b + 1):
            for z in self._bos(j, b, ws, lvl):
                self._merge(prov, z)
        return prov

    def view(self) -> list[PZone]:
        """Zones définitives + provisoires (une provisoire remplace la définitive du même OB
        si son score est ≥, comme le dédoublonnage du scanner)."""
        zones = list(self.zones)
        for z in self.provisional():
            self._merge(zones, z)
        return zones

    def run_to(self, b_last: int) -> None:
        while self.b < b_last:
            self.step()

    def active(self, min_score: int = 4) -> list[PZone]:
        ws = max(0, self.b - self.L + 1)
        return [z for z in self.view() if z.status == ST_ACTIVE and z.score() >= min_score and z.ob >= ws]

    def listed(self, min_score: int = 4) -> list[PZone]:
        """Toutes les zones que le scanner aurait listées (actives ≥ min, + historiques)."""
        return [z for z in self.view() if z.score_pre() >= min_score]


def epoch_seconds(idx) -> np.ndarray:
    """DatetimeIndex (UTC, toute résolution) → secondes epoch."""
    import pandas as pd

    idx = pd.DatetimeIndex(idx)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return np.asarray((idx - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1), dtype=np.int64)


def run_df(df, tf: str, **over) -> PineEngine:
    t = epoch_seconds(df.index)
    eng = PineEngine(df["open"].values, df["high"].values, df["low"].values, df["close"].values, t, tf, **over)
    eng.run_to(len(df) - 1)
    return eng
