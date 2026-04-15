import pandas as pd
supplier_id = "S001"
delay_days = 2
low_quality = True

master_path = "data_base/supplier_master.csv"
master_df = pd.read_csv(master_path)
master_df.columns = master_df.columns.str.strip()
master_df['supplier_id'] = master_df['supplier_id'].astype(str).str.strip()
supplier_id_clean = str(supplier_id).strip()

mask_master = master_df["supplier_id"] == supplier_id_clean
print(f"Mask sum: {mask_master.sum()}")

if mask_master.sum() > 0:
    idx_master = master_df[mask_master].index[0]
    curr_reliability = float(master_df.loc[idx_master, "reliability_score"])
    
    score_adjustment = 0.0
    if low_quality:
        score_adjustment -= 0.05
    else:
        score_adjustment += 0.01  
        
    if delay_days > 0:
        delay_penalty = min(0.05, delay_days * 0.01)
        score_adjustment -= delay_penalty
    elif delay_days < 0:
        score_adjustment += 0.01 
        
    new_reliability = round(curr_reliability + score_adjustment, 2)
    new_reliability = max(0.01, min(1.00, new_reliability))
    
    master_df.loc[idx_master, "reliability_score"] = new_reliability
    print(f"Old: {curr_reliability} New: {new_reliability}")
    master_df.to_csv(master_path, index=False)
    print("Saved")
else:
    print("Not found")
