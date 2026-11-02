"""Baci model v7. B2B = Baci Backoffice (+Faire). Everything else DTC. 3% chargebacks/returns rule."""
COST=0.19                          # G Shopify unitCost / retail (ex freight & duty)
DTC_DISC=7830/109980 + 0.0      # G online+FB/IG+Shop discount rate 7.1%
B2B_OFF=14195/28510                # G Baci Backoffice: 49.8% off retail = keystone
AOV=101988/1009                   # G DTC net (online, FB/IG, Shop, phone) / orders = $101.08
LABEL=8.0; SHIP_PAID=6768.31/1008  # G owner $8 label; customers paid $6.71/order on online orders
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
    contrib=gp-ship_net-cb-cards-brk-frt-adv-free_goods
    oh=sum((overhead or {}).values())
    return dict(R=R,D=D,B=B,cogs=cogs_d+cogs_b,gp=gp,ship=ship_net,cb=cb,cards=cards,brk=brk+frt,ads=adv,free=free_goods,
                contrib=contrib,overhead=oh,profit=contrib-oh,orders_d=orders_d,lost=lost,fob=(cogs_d+cogs_b)/lp)
