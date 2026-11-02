"""Baci model v8. B2B = Baci Backoffice (+Faire). Everything else DTC. 3% chargebacks/returns rule.

v8 (2026-11-02): LABEL measured, PACK added, OVERHEAD from the owner.
Target set by the owner: $3.33 of DTC sales per ad dollar (ads = 30% of DTC)."""
COST=0.19                          # G Shopify unitCost / retail (ex freight & duty)
DTC_DISC=7830/109980 + 0.0      # G online+FB/IG+Shop discount rate 7.1%
B2B_OFF=14195/28510                # G Baci Backoffice: 49.8% off retail = keystone
AOV=101988/1009                   # G DTC net (online, FB/IG, Shop, phone) / orders = $101.08
LABEL=2247.13/196; SHIP_PAID=6768.31/1008  # G Oct 2026 Shopify label charges / orders shipped = $11.46 (was owner's $8); customers paid $6.71/order
PACK=3.50                          # O packaging per DTC order
OVERHEAD={'warehouse_staff':6500*12,   # O $6,500/mo incl. staff (= old employee $48K + warehouse $30K); flat to ~580 orders/mo
          'tradeshow':50000,            # O separate line
          'software_apps':1000*12,      # O Canva, Omnisend, Shopify, Claude + apps, ~$1,000/mo
          'accountant':300*12}          # A owner doesn't know; $0-$600/mo moves the $100K MER 2.65-2.73. Insurance: none on record
CB_RATE=0.03; CB_FEE=15.0          # owner: 3% of DTC orders charged back/returned; $15 + goods + shipping lost
CARD_D=0.03; CARD_B=0.015; BRK_B=0.02; FRT_OUT_B=0.02   # A
DUTY=0.224; FEES=0.012             # G measured on three 2026 entries
def landed_pct_fob(freight, fx, duty=DUTY): return 1+freight+fx+FEES+duty
def pnl(R, b2b, ads, freight, fx=0.02, duty=DUTY, free_goods=0.0, overhead=None):
    B=R*b2b; D=R-B
    lp=landed_pct_fob(freight,fx,duty)
    cogs_d=D/(1-DTC_DISC)*COST*lp; cogs_b=B/(1-B2B_OFF)*COST*lp
    orders_d=D/AOV or 1e-9
    ship_net=orders_d*(LABEL-SHIP_PAID)
    lost=orders_d*CB_RATE/(1-CB_RATE)                     # orders lost to chargeback/return, on top of kept orders
    cb=lost*(CB_FEE+LABEL)+(cogs_d*CB_RATE/(1-CB_RATE))
    cards=CARD_D*D+CARD_B*B; brk=BRK_B*B; frt=FRT_OUT_B*B
    adv=ads*D
    gp=R-cogs_d-cogs_b
    pack=orders_d*PACK
    contrib=gp-ship_net-pack-cb-cards-brk-frt-adv-free_goods
    oh=sum((overhead or {}).values())
    return dict(R=R,D=D,B=B,cogs=cogs_d+cogs_b,gp=gp,ship=ship_net,pack=pack,cb=cb,cards=cards,brk=brk+frt,ads=adv,free=free_goods,
                contrib=contrib,overhead=oh,profit=contrib-oh,orders_d=orders_d,lost=lost,fob=(cogs_d+cogs_b)/lp)
