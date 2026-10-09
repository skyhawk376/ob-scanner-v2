//+------------------------------------------------------------------+
//|                                               OB_Kasper_v3.mq5   |
//|  Expert Advisor : portage fidèle du scanner OB v3 « Kasper »       |
//|  Source de vérité : backend/app/v3/ (params, detect, patterns,   |
//|  sim) + STRATEGY_V3.md du dépôt ob-scanner-v2-fly.               |
//|                                                                  |
//|  Principe : machine à états « streaming » identique à sim.py,     |
//|  alimentée par les bougies CLÔTURÉES de la TF inférieure (LTF)   |
//|  puis par la clôture de la bougie de la TF de zone (HTF).        |
//|  Aucune bougie en cours n'est jamais lue (pas de repaint).       |
//|  Parité vérifiée par mt5/parity_check.py (réplique Python).      |
//+------------------------------------------------------------------+
#property copyright "Oscar ALEXANDRE"
#property version   "3.00"
#property description "OB + FVG, 5 étoiles (Tendance, Liquidité, Vierge, Fibo 0.5, Session), déclencheur LTF, BE +1R, TP 2R"

#include <Trade\Trade.mqh>

//--- modes d'heure serveur
enum ENUM_SRV_TIME
  {
   SRV_AUTO     = 0,   // Auto (live : mesure TimeGMT ; testeur : NY-close)
   SRV_NY_CLOSE = 1,   // NY-close : GMT+2 hiver / GMT+3 été US (IC, Pepperstone, FTMO...)
   SRV_EU_DST   = 2,   // Décalage manuel + heure d'été européenne
   SRV_FIXED    = 3    // Décalage manuel fixe (sans heure d'été)
  };

//====================================================================
// Paramètres (valeurs par défaut = app/v3/params.py)
//====================================================================
input group "=== Zone / détection ==="
input ENUM_TIMEFRAMES InpZoneTF       = PERIOD_H1; // TF de la zone (M5,M15,M30,H1,H4,D1,W1)
input int      InpAtrPeriod           = 14;    // ATR (Wilder) sur la TF de zone
input double   InpImpulseAtr          = 1.0;   // Impulsion : extrême des 3 bougies >= x ATR au-delà du bord proximal
input bool     InpFvgRequired         = true;  // FVG obligatoire dans l'impulsion
input int      InpMaxAgeBars          = 300;   // Expiration (bougies TF zone après l'OB)
input int      InpHistoryBars         = 1000;  // Bougies HTF chargées pour ATR / pivots
input int      InpWarmupBars          = 300;   // Bougies HTF rejouées au démarrage (sans trader)

input group "=== Étoiles ==="
input int      InpMinStars            = 4;     // Étoiles minimum (sur les étoiles actives)
input bool     InpStarTrend           = true;  // Étoile Tendance (Dow, pivots 3/3)
input bool     InpStarLiquidity       = true;  // Étoile Liquidité prise
input bool     InpStarVirgin          = true;  // Étoile Jamais touché
input bool     InpStarFibo            = true;  // Étoile Fibo 0.5
input bool     InpStarSession         = true;  // Étoile Session 08:00-21:00 Paris

input group "=== Déclencheur (TF inférieure) ==="
input bool     InpTrigEngulf          = true;  // Englobante
input bool     InpTrigPin             = true;  // Marteau / étoile filante
input int      InpWindowBars          = 3;     // Fenêtre (bougies TF zone depuis le toucher)
input double   InpAtZoneAtr           = 0.10;  // La bougie doit atteindre la zone à x ATR près
input int      InpMaxTouches          = 0;     // Touchers max par zone (0 = illimité, comme sim.py)

input group "=== Gestion du trade ==="
input double   InpSlBufferAtr         = 0.05;  // SL = bord distal -/+ x ATR
input double   InpTpR                 = 2.0;   // TP en R
input double   InpBeAtR               = 1.0;   // Break-even à +x R (0 = désactivé)
input int      InpBeOffsetPts         = 0;     // Décalage du BE (points)
input bool     InpBeAddSpread         = false; // Ajouter le spread courant au BE
input double   InpRiskPct             = 0.5;   // Risque % du solde (0 = lots fixes)
input double   InpFixedLots           = 0.01;  // Lots fixes si risque = 0
input int      InpMaxTrades           = 3;     // Trades simultanés max (ce symbole + magic)
input int      InpMaxSpreadPts        = 0;     // Spread max en points (0 = pas de filtre)
input int      InpSlippagePts         = 20;    // Déviation max (points)
input ulong    InpMagic               = 330303;// Magic number

input group "=== Heure serveur ==="
input ENUM_SRV_TIME InpSrvMode        = SRV_AUTO; // Mode heure serveur
input double   InpSrvOffsetHours      = 2.0;   // Décalage GMT manuel (hiver pour SRV_EU_DST)

input group "=== Sorties ==="
input bool     InpDraw                = true;  // Dessiner les zones (visuel / live)
input bool     InpCommonFiles         = true;  // CSV dans le dossier commun (Terminal\Common\Files)
input string   InpFilePrefix          = "OBK3"; // Préfixe des fichiers CSV

//====================================================================
// Constantes de la stratégie (non optimisables, cf. params.py)
//====================================================================
#define IMPULSE_BARS   3
#define PIVOT_N        3
#define LIQ_LOOKBACK   30
#define SWEEP_WIN      3
#define FIB_LEVEL      0.5
#define PIN_WICK_BODY  2.0
#define MIN_BODY_FRAC  0.05

#define PH_ACTIVE   0   // armée, attend un toucher
#define PH_WINDOW   1   // touchée, attend la bougie de retournement LTF
#define PH_WAITOUT  2   // doit ressortir de la zone avant un nouveau toucher

#define ST_LIVE     0
#define ST_TRADE    1
#define ST_MISSED   2   // déclencheur déjà passé quand l'EA a connu la zone (rattrapage)
#define ST_SKIPPED  3   // déclencheur valide mais trade refusé (spread, lots, stops, max trades...)
#define ST_INVALID  4
#define ST_EXPIRED  5

//====================================================================
// Structures
//====================================================================
struct SZone
  {
   string            id;
   bool              bull;
   datetime          obTime;      // ouverture bougie OB (heure serveur)
   double            lo, hi, atr;
   double            prox, dist, sl;
   double            ext;         // extrême de l'impulsion jusqu'à la bougie précédente (Fibo)
   bool              sTrend, sLiq, sSess;
   int               armedRel;    // indice relatif (OB = 0) de la bougie d'armement
   int               cur;         // indice relatif de la bougie HTF en cours
   int               pos;         // indice relatif à partir duquel la phase s'applique
   int               tRel;        // bougie du toucher
   int               phase;
   int               state;
   int               nTouch;
   datetime          winEnd;      // fin de fenêtre (heure serveur)
   datetime          jStart;      // première bougie LTF qui touche
   int               touchScore;
   string            touchStars;
   string            trigger;
   datetime          trigTime;    // clôture de la bougie de retournement
   double            entry, tp, lots;
   ulong             posId;
   datetime          endTime;
   string            note;
  };

struct STrack
  {
   ulong             posId;
   string            zoneId;
   bool              bull;
   double            entry, sl0, risk;
   bool              be;
  };

//====================================================================
// Globales
//====================================================================
CTrade          g_trade;
ENUM_TIMEFRAMES g_htf, g_ltf;
int             g_htfSec, g_ltfSec;
datetime        g_lastLtf    = 0;   // ouverture de la dernière bougie LTF traitée
datetime        g_curHtfOpen = 0;   // ouverture de la bougie HTF en cours de traitement
MqlRates        g_prevLtf;
bool            g_havePrev   = false;
SZone           g_zones[];
STrack          g_tracks[];
int             g_srvMode;
int             g_fixedOff = 0;   // décalage fixe (s), manuel ou mesuré
int             g_fhZones = INVALID_HANDLE, g_fhTrades = INVALID_HANDLE;
bool            g_draw = false;
string          g_tfName;

//====================================================================
// Utilitaires TF
//====================================================================
string TfName(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D";
      case PERIOD_W1:  return "W";
     }
   return EnumToString(tf);
  }

// LOWER_TF de params.py
ENUM_TIMEFRAMES LowerTf(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_M5:  return PERIOD_M1;
      case PERIOD_M15: return PERIOD_M5;
      case PERIOD_M30: return PERIOD_M15;
      case PERIOD_H1:  return PERIOD_M15;
      case PERIOD_H4:  return PERIOD_H1;
      case PERIOD_D1:  return PERIOD_H4;
      case PERIOD_W1:  return PERIOD_D1;
     }
   return PERIOD_CURRENT;
  }

//====================================================================
// Heures : serveur -> UTC -> Paris (règles DST US / UE)
//====================================================================
datetime MakeDate(int y, int m, int d, int hh)
  {
   MqlDateTime s;
   ZeroMemory(s);
   s.year = y; s.mon = m; s.day = d; s.hour = hh; s.min = 0; s.sec = 0;
   return StructToTime(s);
  }

int DayOfWeek(datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return s.day_of_week;           // 0 = dimanche
  }

// n-ième dimanche du mois (n >= 1), à l'heure hh UTC
datetime NthSunday(int y, int m, int n, int hh)
  {
   datetime first = MakeDate(y, m, 1, hh);
   int dw = DayOfWeek(first);
   int day = 1 + (7 - dw) % 7 + 7 * (n - 1);
   return MakeDate(y, m, day, hh);
  }

// dernier dimanche d'un mois de 31 jours (mars, octobre)
datetime LastSunday31(int y, int m, int hh)
  {
   datetime last = MakeDate(y, m, 31, hh);
   return last - (datetime)(DayOfWeek(last) * 86400);
  }

bool IsEuDst(datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   return (utc >= LastSunday31(s.year, 3, 1) && utc < LastSunday31(s.year, 10, 1));
  }

bool IsUsDst(datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   return (utc >= NthSunday(s.year, 3, 2, 7) && utc < NthSunday(s.year, 11, 1, 6));
  }

// décalage serveur - GMT (secondes) pour une heure serveur donnée
int SrvOffsetSec(datetime srv)
  {
   int base = (int)MathRound(InpSrvOffsetHours * 3600.0);
   switch(g_srvMode)
     {
      case SRV_NY_CLOSE: return IsUsDst(srv - 2 * 3600) ? 3 * 3600 : 2 * 3600;
      case SRV_EU_DST:   return IsEuDst(srv - base) ? base + 3600 : base;
      case SRV_FIXED:    return g_fixedOff;
     }
   return base;
  }

datetime SrvToUtc(datetime srv) { return srv - (datetime)SrvOffsetSec(srv); }

datetime UtcToParis(datetime utc) { return utc + (datetime)(IsEuDst(utc) ? 7200 : 3600); }

string IsoUtc(datetime srv)
  {
   if(srv <= 0)
      return "";
   string s = TimeToString(SrvToUtc(srv), TIME_DATE | TIME_SECONDS);
   StringReplace(s, ".", "-");
   StringReplace(s, " ", "T");
   return s + "+00:00";
  }

// Mode Auto : en live on mesure, dans le testeur TimeGMT() == heure serveur -> NY-close
void ResolveServerMode()
  {
   g_srvMode = (int)InpSrvMode;
   g_fixedOff = (int)MathRound(InpSrvOffsetHours * 3600.0);
   if(InpSrvMode != SRV_AUTO)
      return;
   if(MQLInfoInteger(MQL_TESTER))
     {
      g_srvMode = SRV_NY_CLOSE;
      Print("Heure serveur : testeur -> hypothèse NY-close (GMT+2/+3). Forcer InpSrvMode si votre courtier diffère.");
      return;
     }
   long meas = (long)(TimeTradeServer() - TimeGMT());
   meas = (long)MathRound(meas / 900.0) * 900;               // arrondi au 1/4 h
   datetime now = TimeTradeServer();
   int ny = IsUsDst(now - 2 * 3600) ? 3 * 3600 : 2 * 3600;
   if(meas == ny)
      g_srvMode = SRV_NY_CLOSE;
   else
     {
      g_srvMode = SRV_FIXED;
      g_fixedOff = (int)meas;
      Print("Heure serveur : décalage mesuré ", meas / 3600.0, " h (fixe). Vérifier le mode si le courtier suit une heure d'été.");
     }
  }

// ★ Session : bougie OB ouverte lun-ven [08:00, 21:00) Paris ; jamais sur D/W
bool InSession(datetime srvOpen)
  {
   if(!(g_htf == PERIOD_M5 || g_htf == PERIOD_M15 || g_htf == PERIOD_M30 || g_htf == PERIOD_H1 || g_htf == PERIOD_H4))
      return false;
   datetime utc = SrvToUtc(srvOpen);
   MqlDateTime s;
   TimeToStruct(UtcToParis(utc), s);
   if(s.day_of_week < 1 || s.day_of_week > 5)
      return false;
   int mins = s.hour * 60 + s.min;
   return (mins >= 8 * 60 && mins < 21 * 60);
  }

//====================================================================
// Indicateurs (calculés sur des bougies clôturées, ordre chronologique)
//====================================================================
// ATR de Wilder : graine = moyenne des n premiers TR (identique à detect.atr)
double AtrAt(const MqlRates &r[], int idx, int n)
  {
   if(idx < n - 1)
      return 0.0;
   double a = 0.0;
   for(int k = 0; k < n; k++)
      a += TrueRange(r, k);
   a /= n;
   for(int k = n; k <= idx; k++)
      a = (a * (n - 1) + TrueRange(r, k)) / n;
   return a;
  }

double TrueRange(const MqlRates &r[], int k)
  {
   if(k == 0)
      return r[0].high - r[0].low;
   double pc = r[k - 1].close;
   return MathMax(r[k].high - r[k].low, MathMax(MathAbs(r[k].high - pc), MathAbs(r[k].low - pc)));
  }

// pivot fractal strict N/N (unique extrême de la fenêtre 2N+1)
bool IsPivot(const MqlRates &r[], int n, int p, bool high)
  {
   if(p - PIVOT_N < 0 || p + PIVOT_N >= n)
      return false;
   for(int q = p - PIVOT_N; q <= p + PIVOT_N; q++)
     {
      if(q == p)
         continue;
      if(high && r[q].high >= r[p].high)
         return false;
      if(!high && r[q].low <= r[p].low)
         return false;
     }
   return true;
  }

// ★ Tendance (Dow) : +1 HH+HL, -1 LH+LL, 0 range ; pivots confirmés (p+N <= i)
int DowTrend(const MqlRates &r[], int n, int i)
  {
   int h1 = -1, h2 = -1, l1 = -1, l2 = -1;  // h2 = dernier, h1 = avant-dernier
   for(int p = i - PIVOT_N; p >= 0 && (h1 < 0 || l1 < 0); p--)
     {
      if(h1 < 0 && IsPivot(r, n, p, true))
        {
         if(h2 < 0) h2 = p; else h1 = p;
        }
      if(l1 < 0 && IsPivot(r, n, p, false))
        {
         if(l2 < 0) l2 = p; else l1 = p;
        }
     }
   if(h1 < 0 || l1 < 0)
      return 0;
   if(r[h2].high > r[h1].high && r[l2].low > r[l1].low)
      return 1;
   if(r[h2].high < r[h1].high && r[l2].low < r[l1].low)
      return -1;
   return 0;
  }

// ★ Liquidité prise : pivot non pris de [i-30, i-3] percé par une mèche de [i-2 .. i]
bool LiquiditySwept(const MqlRates &r[], int n, int i, bool bull)
  {
   int s0 = i - SWEEP_WIN + 1;
   if(s0 <= 0)
      return false;
   double sweep = bull ? DBL_MAX : -DBL_MAX;
   for(int q = s0; q <= i; q++)
      sweep = bull ? MathMin(sweep, r[q].low) : MathMax(sweep, r[q].high);
   for(int p = MathMax(0, i - LIQ_LOOKBACK); p < s0; p++)
     {
      if(p + PIVOT_N > i || !IsPivot(r, n, p, !bull))
         continue;
      double lvl = bull ? r[p].low : r[p].high;
      bool untaken = true;
      for(int q = p + 1; q < s0 && untaken; q++)
         if((bull && r[q].low < lvl) || (!bull && r[q].high > lvl))
            untaken = false;
      if(untaken && ((bull && sweep < lvl) || (!bull && sweep > lvl)))
         return true;
     }
   return false;
  }

//====================================================================
// Bougie de retournement (patterns.reversal_kind)
//====================================================================
string ReversalKind(bool bull, const MqlRates &pv, const MqlRates &c)
  {
   double rng = c.high - c.low;
   if(rng <= 0.0)
      return "";
   double body = MathMax(MathAbs(c.close - c.open), MIN_BODY_FRAC * rng);
   if(bull)
     {
      if(InpTrigEngulf && pv.close < pv.open && c.close > c.open && c.open <= pv.close && c.close >= pv.open)
         return "englobante";
      double lower = MathMin(c.open, c.close) - c.low;
      if(InpTrigPin && lower >= PIN_WICK_BODY * body && c.close >= c.high - rng / 3.0)
         return "marteau";
     }
   else
     {
      if(InpTrigEngulf && pv.close > pv.open && c.close < c.open && c.open >= pv.close && c.close <= pv.open)
         return "englobante";
      double upper = c.high - MathMax(c.open, c.close);
      if(InpTrigPin && upper >= PIN_WICK_BODY * body && c.close <= c.low + rng / 3.0)
         return "etoile filante";
     }
   return "";
  }

//====================================================================
// Étoiles au moment du toucher
//====================================================================
int ZoneStars(const SZone &z, string &flags)
  {
   bool fib;
   if(z.bull)
      fib = (z.hi <= z.lo + FIB_LEVEL * (z.ext - z.lo));
   else
      fib = (z.lo >= z.hi - FIB_LEVEL * (z.hi - z.ext));
   bool virgin = (z.nTouch == 1);
   int sc = 0;
   flags = "";
   if(InpStarTrend && z.sTrend)        { sc++; flags += "T"; }
   if(InpStarLiquidity && z.sLiq)      { sc++; flags += "L"; }
   if(InpStarVirgin && virgin)         { sc++; flags += "V"; }
   if(InpStarFibo && fib)              { sc++; flags += "F"; }
   if(InpStarSession && z.sSess)       { sc++; flags += "S"; }
   return sc;
  }

//====================================================================
// Détection à la clôture de la bougie D = OB+3 (r[n-1])
//====================================================================
void DetectAt(const MqlRates &r[], int n)
  {
   int i = n - 1 - IMPULSE_BARS;
   if(i < InpAtrPeriod + 2 * PIVOT_N)
      return;
   double av = AtrAt(r, i, InpAtrPeriod);
   if(av <= 0.0)
      return;
   for(int d = 0; d < 2; d++)
     {
      bool bull = (d == 0);
      // couleur opposée au mouvement, bougie suivante dans le sens du mouvement
      if(bull && !(r[i].close < r[i].open && r[i + 1].close > r[i + 1].open))
         continue;
      if(!bull && !(r[i].close > r[i].open && r[i + 1].close < r[i + 1].open))
         continue;
      int last = i + IMPULSE_BARS;
      double ext = bull ? -DBL_MAX : DBL_MAX;
      for(int k = i + 1; k <= last; k++)
         ext = bull ? MathMax(ext, r[k].high) : MathMin(ext, r[k].low);
      if(bull && ext - r[i].high < InpImpulseAtr * av)
         continue;
      if(!bull && r[i].low - ext < InpImpulseAtr * av)
         continue;
      // FVG dans l'impulsion (bougies k-1, k, k+1 avec k+1 <= OB+3)
      int kf = -1;
      for(int k = i + 1; k < last; k++)
        {
         if((bull && r[k + 1].low > r[k - 1].high) || (!bull && r[k + 1].high < r[k - 1].low))
           {
            kf = k;
            break;
           }
        }
      if(kf < 0 && InpFvgRequired)
         continue;
      SZone z;
      z.bull     = bull;
      z.obTime   = r[i].time;
      z.id       = TfName(g_htf) + "|" + (bull ? "bull" : "bear") + "|" + IsoUtc(r[i].time);
      if(FindZone(z.id) >= 0)
         continue;
      z.lo       = r[i].low;
      z.hi       = r[i].high;
      z.atr      = av;
      z.prox     = bull ? z.hi : z.lo;
      z.dist     = bull ? z.lo : z.hi;
      z.sl       = bull ? z.dist - InpSlBufferAtr * av : z.dist + InpSlBufferAtr * av;
      z.sTrend   = (DowTrend(r, n, i) == (bull ? 1 : -1));
      z.sLiq     = LiquiditySwept(r, n, i, bull);
      z.sSess    = InSession(r[i].time);
      z.armedRel = (kf >= 0) ? kf + 2 - i : IMPULSE_BARS;
      // extrême de la jambe sur OB..OB+2 ; la bougie D (OB+3) est rejouée juste après
      z.ext      = bull ? z.hi : z.lo;
      for(int k = i + 1; k < last; k++)
         z.ext = bull ? MathMax(z.ext, r[k].high) : MathMin(z.ext, r[k].low);
      z.cur = IMPULSE_BARS;
      z.pos = z.armedRel;
      z.tRel = -1;
      z.phase = PH_ACTIVE;
      z.state = ST_LIVE;
      z.nTouch = 0;
      z.winEnd = 0;
      z.jStart = 0;
      z.touchScore = -1;
      z.touchStars = "";
      z.trigger = "";
      z.trigTime = 0;
      z.entry = 0; z.tp = 0; z.lots = 0;
      z.posId = 0;
      z.endTime = 0;
      z.note = "";
      // rattrapage de la bougie D (déjà clôturée) : un déclencheur ici est « missed »
      CatchUpBar(z, r[n - 1]);
      int m = ArraySize(g_zones);
      ArrayResize(g_zones, m + 1);
      g_zones[m] = z;
      DrawZone(g_zones[m]);
     }
  }

int FindZone(const string id)
  {
   for(int k = ArraySize(g_zones) - 1; k >= 0; k--)
      if(g_zones[k].id == id)
         return k;
   return -1;
  }

void CatchUpBar(SZone &z, const MqlRates &hb)
  {
   MqlRates lr[], pv[];
   int cnt = CopyRates(_Symbol, g_ltf, hb.time, hb.time + (datetime)(g_htfSec - 1), lr);
   if(cnt > 0 && CopyRates(_Symbol, g_ltf, lr[0].time - 1, 1, pv) == 1)
     {
      MqlRates prev = pv[0];
      for(int k = 0; k < cnt; k++)
        {
         ZoneOnLtf(z, hb.time, prev, lr[k], true);
         prev = lr[k];
        }
     }
   ZoneOnHtfClose(z, hb);
  }

//====================================================================
// Machine à états (sim.simulate_zone en streaming)
//====================================================================
void ZoneOnLtf(SZone &z, datetime hOpen, const MqlRates &pv, const MqlRates &c, bool past)
  {
   if(z.state != ST_LIVE)
      return;
   if(z.phase == PH_ACTIVE)
     {
      if(z.cur < z.pos || z.cur > InpMaxAgeBars)
         return;
      bool hit = z.bull ? (c.low <= z.prox) : (c.high >= z.prox);
      if(!hit)
         return;
      z.nTouch++;
      string fl;
      int sc = ZoneStars(z, fl);
      z.touchScore = sc;
      z.touchStars = fl;
      if(sc >= InpMinStars && (InpMaxTouches <= 0 || z.nTouch <= InpMaxTouches))
        {
         z.phase  = PH_WINDOW;
         z.tRel   = z.cur;
         z.winEnd = hOpen + (datetime)(InpWindowBars * g_htfSec);
         z.jStart = c.time;
         UpdateLabel(z);
        }
      else
        {
         z.phase = PH_WAITOUT;
         z.pos   = z.cur + 1;
         return;
        }
     }
   if(z.phase == PH_WINDOW)
     {
      if(c.time + (datetime)g_ltfSec > z.winEnd)
        {
         z.phase = PH_WAITOUT;
         z.pos   = (hOpen >= z.winEnd) ? z.cur : z.cur + 1;
         return;
        }
      if(c.time < z.jStart)
         return;
      double a = z.atr;
      bool reach  = z.bull ? (c.low <= z.prox + InpAtZoneAtr * a) : (c.high >= z.prox - InpAtZoneAtr * a);
      bool inside = z.bull ? (c.close > z.sl && c.close > z.dist) : (c.close < z.sl && c.close < z.dist);
      if(!(reach && inside))
         return;
      string kind = ReversalKind(z.bull, pv, c);
      if(kind == "")
         return;
      z.trigger  = kind;
      z.trigTime = c.time + (datetime)g_ltfSec;
      z.entry    = c.close;
      if(past)
        {
         z.state = ST_MISSED;
         z.note  = "declencheur avant que l'EA connaisse/suive la zone";
        }
      else
         OpenTrade(z);
     }
  }

void ZoneOnHtfClose(SZone &z, const MqlRates &b)
  {
   if(z.state == ST_LIVE)
     {
      int r = z.cur;
      bool beyond = z.bull ? (b.close < z.dist) : (b.close > z.dist);
      if(z.phase == PH_ACTIVE && r >= z.pos)
        {
         if(r > InpMaxAgeBars)
            z.state = ST_EXPIRED;
         else
            if(beyond)
               z.state = ST_INVALID;
            else
               if(r >= InpMaxAgeBars)
                  z.state = ST_EXPIRED;
        }
      else
         if(z.phase == PH_WINDOW)
           {
            if(beyond)
               z.state = ST_INVALID;
            else
               if(b.time + (datetime)g_htfSec >= z.winEnd)
                 {
                  z.phase = PH_WAITOUT;
                  z.pos   = r + 1;
                 }
           }
         else
            if(z.phase == PH_WAITOUT && r >= z.pos)
              {
               bool outside = z.bull ? (b.low > z.prox) : (b.high < z.prox);
               if(beyond)
                  z.state = ST_INVALID;
               else
                  if(outside)
                    {
                     z.phase = PH_ACTIVE;
                     z.pos   = r + 1;
                    }
              }
      if(z.state != ST_LIVE)
         z.endTime = b.time + (datetime)g_htfSec;
     }
   z.ext = z.bull ? MathMax(z.ext, b.high) : MathMin(z.ext, b.low);
   z.cur++;
  }

//====================================================================
// Exécution
//====================================================================
int CountMyPositions()
  {
   int n = 0;
   for(int k = PositionsTotal() - 1; k >= 0; k--)
     {
      ulong t = PositionGetTicket(k);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         n++;
     }
   return n;
  }

double NormPrice(double p)
  {
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts > 0.0)
      p = MathRound(p / ts) * ts;
   return NormalizeDouble(p, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));
  }

double CalcLots(bool bull, double price, double sl)
  {
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double lots  = InpFixedLots;
   if(InpRiskPct > 0.0)
     {
      double riskMoney = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0;
      double pl = 0.0;
      double perLot = 0.0;
      if(OrderCalcProfit(bull ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, 1.0, price, sl, pl))
         perLot = MathAbs(pl);
      if(perLot <= 0.0)
        {
         double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
         if(tv <= 0.0) tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
         double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
         if(tv > 0.0 && ts > 0.0)
            perLot = MathAbs(price - sl) / ts * tv;
        }
      if(perLot <= 0.0)
         return 0.0;
      lots = riskMoney / perLot;
     }
   if(vstep > 0.0)
      lots = MathFloor(lots / vstep + 1e-9) * vstep;
   if(lots < vmin)
      return 0.0;                    // trop petit pour respecter le risque : on refuse
   lots = MathMin(lots, vmax);
   return NormalizeDouble(lots, 8);
  }

void SetFilling()
  {
   long fm = SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((fm & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      g_trade.SetTypeFilling(ORDER_FILLING_FOK);
   else
      if((fm & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
         g_trade.SetTypeFilling(ORDER_FILLING_IOC);
      else
         g_trade.SetTypeFilling(ORDER_FILLING_RETURN);
  }

void Skip(SZone &z, const string why)
  {
   z.state = ST_SKIPPED;
   z.note  = why;
   z.endTime = z.trigTime;
   PrintFormat("OBK3 %s : déclencheur %s ignoré (%s)", z.id, z.trigger, why);
  }

void OpenTrade(SZone &z)
  {
   if(CountMyPositions() >= InpMaxTrades)        { Skip(z, "max trades");        return; }
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(ask <= 0.0 || bid <= 0.0)                  { Skip(z, "pas de prix");        return; }
   if(InpMaxSpreadPts > 0 && (ask - bid) > InpMaxSpreadPts * pt) { Skip(z, "spread"); return; }
   double price = z.bull ? ask : bid;
   double sl    = NormPrice(z.sl);
   double risk  = z.bull ? price - sl : sl - price;
   if(risk <= 0.0)                               { Skip(z, "prix déjà au-delà du SL"); return; }
   double tp    = NormPrice(z.bull ? price + InpTpR * risk : price - InpTpR * risk);
   double lvl   = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * pt;
   double dSl   = z.bull ? bid - sl : sl - ask;
   double dTp   = z.bull ? tp - bid : ask - tp;
   if(dSl <= lvl || dTp <= lvl)                  { Skip(z, "stops level");        return; }
   double lots = CalcLots(z.bull, price, sl);
   if(lots <= 0.0)                               { Skip(z, "lot < minimum");      return; }
   string cmt = StringFormat("OBK3 %s %d* %s", TfName(g_htf), z.touchScore, z.touchStars);
   bool ok = z.bull ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, cmt)
                    : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, cmt);
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED && rc != TRADE_RETCODE_DONE_PARTIAL))
     {
      Skip(z, "ordre refusé " + IntegerToString((int)rc) + " " + g_trade.ResultRetcodeDescription());
      return;
     }
   double fill = g_trade.ResultPrice();
   if(fill <= 0.0) fill = price;
   ulong posId = g_trade.ResultOrder();
   ulong deal  = g_trade.ResultDeal();
   if(deal > 0 && HistoryDealSelect(deal))
      posId = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
   z.state = ST_TRADE;
   z.posId = posId;
   z.lots  = lots;
   z.tp    = tp;
   z.entry = fill;
   z.endTime = TimeCurrent();
   int m = ArraySize(g_tracks);
   ArrayResize(g_tracks, m + 1);
   g_tracks[m].posId  = posId;
   g_tracks[m].zoneId = z.id;
   g_tracks[m].bull   = z.bull;
   g_tracks[m].entry  = fill;
   g_tracks[m].sl0    = sl;
   g_tracks[m].risk   = MathAbs(fill - sl);
   g_tracks[m].be     = false;
   LogTrade("ENTRY", z.id, z.bull, z.touchScore, z.touchStars, z.trigger, z.trigTime, TimeCurrent(),
            fill, sl, tp, lots, posId, "", 0.0, 0.0, false);
  }

// +1R -> SL à l'entrée (+ décalage) ; R déduit du TP (TP = entrée ± TpR*R)
void ManageBreakEven()
  {
   if(InpBeAtR <= 0.0)
      return;
   double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double lvl = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * pt;
   for(int k = PositionsTotal() - 1; k >= 0; k--)
     {
      ulong t = PositionGetTicket(k);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      bool   buy  = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      if(tp <= 0.0 || InpTpR <= 0.0)
         continue;
      double R = MathAbs(tp - open) / InpTpR;
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double off = InpBeOffsetPts * pt + (InpBeAddSpread ? (ask - bid) : 0.0);
      if(buy)
        {
         if(sl >= open || bid < open + InpBeAtR * R)
            continue;
         double nsl = NormPrice(open + off);
         if(bid - nsl <= lvl || nsl <= sl)
            continue;
         if(g_trade.PositionModify(t, nsl, tp))
            MarkBe(t);
        }
      else
        {
         if((sl > 0.0 && sl <= open) || ask > open - InpBeAtR * R)
            continue;
         double nsl = NormPrice(open - off);
         if(nsl - ask <= lvl || (sl > 0.0 && nsl >= sl))
            continue;
         if(g_trade.PositionModify(t, nsl, tp))
            MarkBe(t);
        }
     }
  }

void MarkBe(ulong posTicket)
  {
   for(int k = 0; k < ArraySize(g_tracks); k++)
      if(g_tracks[k].posId == posTicket)
         g_tracks[k].be = true;
  }

// positions fermées -> ligne EXIT dans le CSV
void CheckClosedTrades()
  {
   for(int k = ArraySize(g_tracks) - 1; k >= 0; k--)
     {
      if(PositionSelectByTicket(g_tracks[k].posId))
         continue;
      if(!HistorySelectByPosition(g_tracks[k].posId))
         continue;
      double profit = 0.0, exitPx = 0.0;
      datetime exitT = 0;
      long reason = -1;
      bool closed = false;
      for(int d = 0; d < HistoryDealsTotal(); d++)
        {
         ulong dt = HistoryDealGetTicket(d);
         if(dt == 0)
            continue;
         profit += HistoryDealGetDouble(dt, DEAL_PROFIT) + HistoryDealGetDouble(dt, DEAL_SWAP) + HistoryDealGetDouble(dt, DEAL_COMMISSION);
         long en = HistoryDealGetInteger(dt, DEAL_ENTRY);
         if(en == DEAL_ENTRY_OUT || en == DEAL_ENTRY_OUT_BY)
           {
            closed = true;
            exitPx = HistoryDealGetDouble(dt, DEAL_PRICE);
            exitT  = (datetime)HistoryDealGetInteger(dt, DEAL_TIME);
            reason = HistoryDealGetInteger(dt, DEAL_REASON);
           }
        }
      if(!closed)
         continue;
      STrack tr = g_tracks[k];
      double rg = (tr.risk > 0.0) ? (tr.bull ? exitPx - tr.entry : tr.entry - exitPx) / tr.risk : 0.0;
      string kind = "close";
      if(reason == DEAL_REASON_TP)
         kind = "tp";
      else
         if(reason == DEAL_REASON_SL)
            kind = tr.be ? "be_exit" : "sl";
      LogTrade("EXIT", tr.zoneId, tr.bull, -1, "", kind, 0, exitT, tr.entry, tr.sl0, exitPx, 0.0,
               tr.posId, kind, rg, profit, tr.be);
      int last = ArraySize(g_tracks) - 1;
      if(k != last)
         g_tracks[k] = g_tracks[last];
      ArrayResize(g_tracks, last);
     }
  }

//====================================================================
// Journal CSV (séparateur ';', horaires en UTC ISO comme le scanner)
//====================================================================
string StateName(int st, int phase)
  {
   switch(st)
     {
      case ST_TRADE:   return "trade";
      case ST_MISSED:  return "missed";
      case ST_SKIPPED: return "skipped";
      case ST_INVALID: return "invalidated";
      case ST_EXPIRED: return "expired";
     }
   if(phase == PH_WINDOW)  return "touched";
   if(phase == PH_WAITOUT) return "waiting";
   return "active";
  }

int OpenCsv(const string name, bool &isNew)
  {
   int flags = FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE;
   if(InpCommonFiles)
      flags |= FILE_COMMON;
   bool tester = (MQLInfoInteger(MQL_TESTER) != 0);
   if(tester)
     {
      int f0 = FileOpen(name, (flags & ~FILE_READ), ';');   // testeur : fichier remis à zéro
      if(f0 != INVALID_HANDLE)
         FileClose(f0);
     }
   int h = FileOpen(name, flags, ';');
   if(h == INVALID_HANDLE)
     {
      Print("Impossible d'ouvrir ", name, " err=", GetLastError());
      return h;
     }
   isNew = (FileSize(h) == 0);
   FileSeek(h, 0, SEEK_END);
   return h;
  }

void LogZone(const SZone &z)
  {
   if(g_fhZones == INVALID_HANDLE)
      return;
   FileWrite(g_fhZones, _Symbol, g_tfName, (z.bull ? "bull" : "bear"), IsoUtc(z.obTime),
             TimeToString(z.obTime, TIME_DATE | TIME_MINUTES),
             DoubleToString(z.lo, _Digits), DoubleToString(z.hi, _Digits), DoubleToString(z.atr, _Digits + 2),
             (int)z.sTrend, (int)z.sLiq, (int)z.sSess, StateName(z.state, z.phase), z.nTouch,
             z.touchScore, z.touchStars, z.trigger, TfName(g_ltf), IsoUtc(z.trigTime),
             DoubleToString(z.entry, _Digits), DoubleToString(NormPrice(z.sl), _Digits),
             DoubleToString(z.tp, _Digits), DoubleToString(z.lots, 2), (long)z.posId,
             IsoUtc(z.endTime), z.note);
   FileFlush(g_fhZones);
  }

void LogTrade(const string ev, const string zid, bool bull, int score, const string stars, const string trig,
              datetime trigT, datetime t, double entry, double sl, double px, double lots, ulong posId,
              const string exitKind, double rGross, double profit, bool be)
  {
   if(g_fhTrades == INVALID_HANDLE)
      return;
   FileWrite(g_fhTrades, ev, _Symbol, g_tfName, zid, (bull ? "bull" : "bear"), score, stars, trig, TfName(g_ltf),
             IsoUtc(trigT), IsoUtc(t), DoubleToString(entry, _Digits), DoubleToString(sl, _Digits),
             DoubleToString(px, _Digits), DoubleToString(lots, 2), (long)posId, exitKind,
             DoubleToString(rGross, 3), DoubleToString(profit, 2), (int)be);
   FileFlush(g_fhTrades);
  }

//====================================================================
// Dessin
//====================================================================
string Stars5(int n)
  {
   string s = "";
   for(int k = 0; k < n; k++)
      s += ShortToString(0x2605);
   return s;
  }

void DrawZone(const SZone &z)
  {
   if(!g_draw)
      return;
   string nm = "OBK3_" + z.id;
   datetime t2 = z.obTime + (datetime)((long)InpMaxAgeBars * g_htfSec);
   if(ObjectFind(0, nm) < 0)
      ObjectCreate(0, nm, OBJ_RECTANGLE, 0, z.obTime, z.lo, t2, z.hi);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, z.bull ? clrLightSkyBlue : clrMistyRose);
   ObjectSetInteger(0, nm, OBJPROP_FILL, true);
   ObjectSetInteger(0, nm, OBJPROP_BACK, true);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   UpdateLabel(z);
  }

void UpdateLabel(const SZone &z)
  {
   if(!g_draw)
      return;
   string nm = "OBK3_" + z.id + "_lbl";
   double p = z.bull ? z.hi : z.lo;
   if(ObjectFind(0, nm) < 0)
      ObjectCreate(0, nm, OBJ_TEXT, 0, z.obTime, p);
   string txt;
   if(z.touchScore >= 0)
      txt = StringFormat("%s %s %d/5 %s #%d", TfName(g_htf), Stars5(z.touchScore), z.touchScore, z.touchStars, z.nTouch);
   else
     {
      string st = (z.sTrend ? "T" : "") + (z.sLiq ? "L" : "") + (z.sSess ? "S" : "");
      txt = StringFormat("%s OB %s (statiques %s)", TfName(g_htf), (z.bull ? "bull" : "bear"), st);
     }
   if(z.trigger != "")
      txt += " -> " + z.trigger;
   ObjectSetString(0, nm, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, z.bull ? clrDodgerBlue : clrTomato);
   ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, nm, OBJPROP_ANCHOR, z.bull ? ANCHOR_LEFT_LOWER : ANCHOR_LEFT_UPPER);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
  }

void CloseDrawing(const SZone &z)
  {
   if(!g_draw)
      return;
   string nm = "OBK3_" + z.id;
   if(ObjectFind(0, nm) >= 0 && z.endTime > 0)
      ObjectSetInteger(0, nm, OBJPROP_TIME, 1, (long)z.endTime);
   if(z.state == ST_INVALID || z.state == ST_EXPIRED)
      ObjectSetInteger(0, nm, OBJPROP_COLOR, clrGainsboro);
   UpdateLabel(z);
  }

//====================================================================
// Boucle d'événements : LTF clôturées puis clôture HTF puis détection
//====================================================================
void FlushFinished()
  {
   for(int k = ArraySize(g_zones) - 1; k >= 0; k--)
     {
      if(g_zones[k].state == ST_LIVE)
         continue;
      LogZone(g_zones[k]);
      CloseDrawing(g_zones[k]);
      int last = ArraySize(g_zones) - 1;
      if(k != last)
         g_zones[k] = g_zones[last];
      ArrayResize(g_zones, last);
     }
  }

void OnHtfClose(const MqlRates &b)
  {
   for(int k = 0; k < ArraySize(g_zones); k++)
      ZoneOnHtfClose(g_zones[k], b);
   FlushFinished();
   MqlRates r[];
   int n = CopyRates(_Symbol, g_htf, b.time, InpHistoryBars, r);
   if(n < InpAtrPeriod + 2 * PIVOT_N + IMPULSE_BARS + 1 || r[n - 1].time != b.time)
      return;
   DetectAt(r, n);
   FlushFinished();
  }

// clôture toutes les bougies HTF ouvertes dans [g_curHtfOpen, newOpen)
void CloseHtfUntil(datetime newOpen)
  {
   if(newOpen <= g_curHtfOpen)
      return;
   MqlRates hr[];
   int n = CopyRates(_Symbol, g_htf, g_curHtfOpen, newOpen - 1, hr);
   for(int k = 0; k < n; k++)
      if(hr[k].time >= g_curHtfOpen && hr[k].time < newOpen)
         OnHtfClose(hr[k]);
   g_curHtfOpen = newOpen;
  }

datetime HtfOpenOf(datetime t)
  {
   int sh = iBarShift(_Symbol, g_htf, t, false);
   if(sh < 0)
      return 0;
   return iTime(_Symbol, g_htf, sh);
  }

void ProcessBars()
  {
   datetime lastClosed = iTime(_Symbol, g_ltf, 1);
   datetime h0 = iTime(_Symbol, g_htf, 0);
   if(lastClosed == 0 || h0 == 0)
      return;                                     // historique pas encore prêt
   if(g_lastLtf == 0)
     {
      // initialisation : on rejoue InpWarmupBars bougies HTF (sans trader : bougies « passées »)
      datetime hStart = iTime(_Symbol, g_htf, MathMax(InpWarmupBars, 1));
      if(hStart == 0)
         hStart = h0;
      MqlRates pv[];
      if(CopyRates(_Symbol, g_ltf, hStart - 1, 1, pv) != 1)
         return;
      g_prevLtf = pv[0];
      g_havePrev = true;
      g_lastLtf = pv[0].time;
      g_curHtfOpen = hStart;
     }
   if(lastClosed > g_lastLtf)
     {
      MqlRates lr[];
      int n = CopyRates(_Symbol, g_ltf, g_lastLtf + 1, lastClosed, lr);
      if(n <= 0)
         return;                                  // données pas prêtes : on réessaiera
      datetime now = TimeCurrent();
      for(int k = 0; k < n; k++)
        {
         if(lr[k].time <= g_lastLtf)
            continue;
         datetime hOpen = HtfOpenOf(lr[k].time);
         if(hOpen > g_curHtfOpen)
            CloseHtfUntil(hOpen);
         // bougie trop ancienne (rattrapage / reconnexion) : pas d'ordre au marché
         long age = (long)now - (long)lr[k].time - (long)g_ltfSec;   // secondes depuis la clôture
         bool past = (age > (long)g_ltfSec);
         for(int z = 0; z < ArraySize(g_zones); z++)
            ZoneOnLtf(g_zones[z], hOpen, g_prevLtf, lr[k], past);
         FlushFinished();
         g_prevLtf = lr[k];
         g_lastLtf = lr[k].time;
        }
     }
   // la bougie HTF précédente est complète dès qu'une nouvelle s'ouvre
   if(h0 > g_curHtfOpen && g_lastLtf + (datetime)g_ltfSec >= h0)
      CloseHtfUntil(h0);
  }

//====================================================================
// Événements MT5
//====================================================================
int OnInit()
  {
   g_htf = InpZoneTF;
   if(g_htf == PERIOD_CURRENT)
      g_htf = (ENUM_TIMEFRAMES)Period();
   g_ltf = LowerTf(g_htf);
   if(g_ltf == PERIOD_CURRENT)
     {
      Print("TF de zone non supportée (M5, M15, M30, H1, H4, D1, W1) : ", EnumToString(g_htf));
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpMinStars < 0 || InpMinStars > 5 || InpTpR <= 0.0 || InpAtrPeriod < 2 || InpWindowBars < 1)
      return INIT_PARAMETERS_INCORRECT;
   g_htfSec = PeriodSeconds(g_htf);
   g_ltfSec = PeriodSeconds(g_ltf);
   g_tfName = TfName(g_htf);
   ResolveServerMode();
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePts);
   g_trade.SetMarginMode();
   SetFilling();
   g_draw = InpDraw && (!MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_VISUAL_MODE));
   bool isNew = false;
   string base = InpFilePrefix + "_" + _Symbol + "_" + g_tfName;
   g_fhZones = OpenCsv(base + "_zones.csv", isNew);
   if(g_fhZones != INVALID_HANDLE && isNew)
      FileWrite(g_fhZones, "symbol", "tf", "dir", "ts_ob_utc", "ts_ob_server", "low", "high", "atr",
                "star_trend", "star_liquidity", "star_session", "state", "n_touch", "touch_score",
                "touch_stars", "trigger", "ltf", "entry_utc", "entry", "sl", "tp", "lots", "position",
                "end_utc", "note");
   g_fhTrades = OpenCsv(base + "_trades.csv", isNew);
   if(g_fhTrades != INVALID_HANDLE && isNew)
      FileWrite(g_fhTrades, "event", "symbol", "tf", "zone_id", "dir", "score", "stars", "trigger", "ltf",
                "trigger_close_utc", "time_utc", "entry", "sl", "price", "lots", "position", "exit",
                "r_gross", "profit", "be");
   // on demande l'historique des deux TF (chargement asynchrone en live)
   iTime(_Symbol, g_htf, 0);
   iTime(_Symbol, g_ltf, 0);
   PrintFormat("OB Kasper v3 : zone %s -> déclencheur %s, min %d étoiles, mode heure serveur %d",
               g_tfName, TfName(g_ltf), InpMinStars, g_srvMode);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   // zones encore vivantes : une ligne d'état final pour la comparaison
   for(int k = 0; k < ArraySize(g_zones); k++)
      LogZone(g_zones[k]);
   CheckClosedTrades();
   if(g_fhZones != INVALID_HANDLE)
      FileClose(g_fhZones);
   if(g_fhTrades != INVALID_HANDLE)
      FileClose(g_fhTrades);
   if(!MQLInfoInteger(MQL_TESTER))
      ObjectsDeleteAll(0, "OBK3_");
  }

void OnTick()
  {
   ProcessBars();
   ManageBreakEven();
   CheckClosedTrades();
  }

double OnTester()
  {
   // critère personnalisé : facteur de profit pondéré par le nombre de trades (évite le sur-ajustement sur 5 trades)
   double trades = TesterStatistics(STAT_TRADES);
   double pf     = TesterStatistics(STAT_PROFIT_FACTOR);
   double dd     = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   if(trades < 30)
      return 0.0;
   return pf * MathSqrt(trades) / (1.0 + dd / 10.0);
  }
//+------------------------------------------------------------------+
