import pandas as pd
import numpy as np
import os

def calculate_abs_error(value, error_percent_min=3, error_percent_max=5):
    """
    คำนวณ absolute error ในช่วงที่กำหนด (3-5%)
    สุ่มเลือกเปอร์เซ็นต์ความผิดพลาดในช่วงที่กำหนด และสุ่มเครื่องหมาย +/-
    """
    if pd.isna(value) or value == 0:
        return 0
    
    # สุ่มเปอร์เซ็นต์ความผิดพลาดระหว่าง 3-5%
    error_percent = np.random.uniform(error_percent_min, error_percent_max)
    
    # สุ่มเครื่องหมาย +/- 
    sign = np.random.choice([-1, 1])
    
    # คำนวณค่าความผิดพลาด
    error = value * (error_percent / 100) * sign
    
    # คำนวณค่าที่มีความผิดพลาด
    result = value + error
    
    # ตรวจสอบไม่ให้เป็นค่าลบ (ถ้าเป็นข้อมูลที่ไม่ควรเป็นลบ)
    if result < 0:
        result = abs(result)
    
    return round(result, 2)

def process_excel_to_txt(excel_file_path):
    """
    ประมวลผลไฟล์ Excel และสร้างไฟล์ .txt ตามชีทต่างๆ
    """
    try:
        # อ่านไฟล์ Excel
        excel_file = pd.ExcelFile(excel_file_path)
        print(f"พบชีททั้งหมด {len(excel_file.sheet_names)} ชีท")
        
        # วนลูปผ่านแต่ละชีท
        for sheet_name in excel_file.sheet_names:
            # ข้ามชีท Analysis
            if sheet_name.lower() == 'analysis':
                print(f"ข้ามชีท: {sheet_name}")
                continue
            
            print(f"กำลังประมวลผลชีท: {sheet_name}")
            
            # อ่านข้อมูลจากชีท
            df = pd.read_excel(excel_file_path, sheet_name=sheet_name, header=None)
            
            # ตรวจสอบว่ามีคอลัมน์ F (index 5) หรือไม่
            if len(df.columns) < 6:
                print(f"  ชีท {sheet_name} ไม่มีคอลัมน์ F - ข้าม")
                continue
            
            # ดึงข้อมูลจากคอลัมน์ F เริ่มจากแถว 3 (index 2)
            col_f_data = df.iloc[2:, 5]  # คอลัมน์ F จากแถว 3 เป็นต้นไป
            
            # ประมวลผลข้อมูลทั้งหมด รวมช่องว่าง
            processed_data = []
            valid_count = 0
            
            for val in col_f_data:
                if pd.isna(val):
                    # ช่องว่าง ใส่ค่า 0
                    processed_data.append(0)
                elif isinstance(val, (int, float)):
                    if val == 0:
                        processed_data.append(0)
                    else:
                        # คำนวณ abs error สำหรับค่าที่ไม่เป็น 0
                        error_value = calculate_abs_error(float(val))
                        processed_data.append(error_value)
                        valid_count += 1
                # ข้ามค่าที่ไม่ใช่ตัวเลข (เช่น text)
            
            if len(processed_data) == 0:
                print(f"  ชีท {sheet_name} ไม่มีข้อมูลในคอลัมน์ F - ใส่ค่า 0")
                processed_data = [0]
            else:
                print(f"  พบข้อมูล {len(processed_data)} รายการ (ข้อมูลตัวเลขที่ไม่เป็น 0: {valid_count} รายการ)")
            
            # สร้างโฟลเดอร์ results ถ้ายังไม่มี
            results_dir = "results"
            if not os.path.exists(results_dir):
                os.makedirs(results_dir)
            
            # สร้างชื่อไฟล์ output
            # แปลงชื่อชีทเป็นตัวพิมพ์ใหญ่และเพิ่ม VA_ ข้างหน้า
            output_filename = os.path.join(results_dir, f"VA_{sheet_name.upper()}.txt")
            
            # เขียนข้อมูลลงไฟล์
            with open(output_filename, 'w', encoding='utf-8') as f:
                for value in processed_data:
                    f.write(f"{value}\n")
            
            print(f"  สร้างไฟล์: {output_filename} ({len(processed_data)} รายการ)")
        
        print("\nเสร็จสิ้นการประมวลผล!")
        
    except Exception as e:
        print(f"เกิดข้อผิดพลาด: {e}")

def main():
    # ลิสต์ไฟล์ Excel ที่ต้องการประมวลผล
    excel_files = [
        "RAOT2568_CE-Biomass & Carbon Stock.xlsx",
        "RAOT2568_US-Biomass _ Carbon Stock_3 July 2025_Edit-LS01.xlsx"
    ]
    
    for excel_file in excel_files:
        # ตรวจสอบว่าไฟล์มีอยู่หรือไม่
        if not os.path.exists(excel_file):
            print(f"ไม่พบไฟล์: {excel_file} - ข้าม")
            continue
        
        print(f"\n{'='*60}")
        print(f"เริ่มประมวลผลไฟล์: {excel_file}")
        print(f"{'='*60}")
        process_excel_to_txt(excel_file)

if __name__ == "__main__":
    main()
