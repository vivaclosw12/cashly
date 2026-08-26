
import io, re
from decimal import Decimal
import pandas as pd
from db import SessionLocal,Click,Conversion,Ledger

ALIASES={
 "sub_id":["sub_id","sub id","subid","utm_content"],
 "order_id":["order_id","order id","orderid","ordersn","order sn"],
 "order_amount":["order_amount","order amount","sale amount","gmv","item price","sales amount"],
 "commission_amount":["commission_amount","commission amount","commission","payout","estimated commission"],
 "status":["status","conversion status","order status","validation status"],
}

def norm(s): return re.sub(r"\s+"," ",str(s).strip().lower())

def pick_col(cols,names):
    m={norm(c):c for c in cols}
    for n in names:
        if norm(n) in m:return m[norm(n)]
    return None

def map_status(v):
    x=norm(v)
    if any(k in x for k in ["confirm","approve","valid","complete","paid"]):return "confirmed"
    if any(k in x for k in ["reject","cancel","invalid","refund","void"]):return "rejected"
    return "pending"

def import_report(raw:bytes,filename:str,user_share_percent:Decimal):
    if filename.lower().endswith(".csv"):
        df=pd.read_csv(io.BytesIO(raw))
    else:
        df=pd.read_excel(io.BytesIO(raw))
    cols=list(df.columns)
    found={k:pick_col(cols,v) for k,v in ALIASES.items()}
    required=["sub_id","order_id","commission_amount"]
    missing=[x for x in required if not found[x]]
    if missing:
        return {"ok":False,"missing":missing,"columns":[str(x) for x in cols]}

    stats={"rows":0,"matched":0,"created":0,"updated":0,"unmatched":0}
    with SessionLocal() as db:
        for _,r in df.iterrows():
            stats["rows"]+=1
            sub=str(r[found["sub_id"]]).strip()
            click=db.query(Click).filter(Click.sub_id==sub).first()
            if not click:
                stats["unmatched"]+=1;continue
            stats["matched"]+=1
            order_id=str(r[found["order_id"]]).strip()
            commission=Decimal(str(r[found["commission_amount"]] or 0))
            order_amount=Decimal(str(r[found["order_amount"]] or 0)) if found["order_amount"] else Decimal("0")
            status=map_status(r[found["status"]]) if found["status"] else "pending"
            cashback=(commission*user_share_percent/Decimal("100")).quantize(Decimal("1"))
            revenue=commission-cashback
            c=db.query(Conversion).filter(Conversion.merchant_id==click.merchant_id,Conversion.order_id==order_id).first()
            if not c:
                c=Conversion(merchant_id=click.merchant_id,click_id=click.click_id,sub_id=sub,order_id=order_id,
                    order_amount=order_amount,commission_amount=commission,cashback_amount=cashback,
                    platform_revenue=revenue,status=status,source="report_import")
                db.add(c);db.flush();stats["created"]+=1
            else:
                old=c.status
                c.order_amount=order_amount;c.commission_amount=commission;c.cashback_amount=cashback;c.platform_revenue=revenue;c.status=status;c.source="report_import"
                stats["updated"]+=1

            existing_credit=db.query(Ledger).filter(Ledger.reference==order_id,Ledger.entry_type=="cashback_credit").first()
            if status=="confirmed" and not existing_credit:
                db.add(Ledger(user_id=click.user_id,entry_type="cashback_credit",amount=cashback,reference=order_id,note="Imported confirmed cashback"))
            if status=="rejected" and existing_credit:
                existing_reversal=db.query(Ledger).filter(Ledger.reference==order_id,Ledger.entry_type=="cashback_reversal").first()
                if not existing_reversal:
                    db.add(Ledger(user_id=click.user_id,entry_type="cashback_reversal",amount=-cashback,reference=order_id,note="Imported cashback reversal"))
        db.commit()
    return {"ok":True,**stats,"columns":found}
