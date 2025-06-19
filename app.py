import os, time, re
from datetime import datetime
from collections import Counter

from flask import (
    Flask, render_template, request,
    redirect, url_for
)
from flask import send_file
import pandas as pd
import instaloader
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


app = Flask(__name__)
app.secret_key = "super_secret_key_1289"
REPORT_PATH = os.path.join(app.root_path, "instagram_report.xlsx")

@app.route('/', methods=['GET'])
def index():
    # 기존 form.html 사용
    return render_template("form2.html")

@app.route('/start', methods=['POST'])
def start():
    account_url = request.form['account_url'].rstrip('/')
    count       = min(int(request.form.get('count', 5)), 10)

    # 계정명, Instaloader 초기화
    profile_name = account_url.split('/')[-1]
    L = instaloader.Instaloader()
    L.login("jaeho._yoon", "dkssud881!")  # 로그인 계정 사용
    profile = instaloader.Profile.from_username(L.context, profile_name)

    options = Options()
    options.add_argument('--headless')             # 창을 띄우지 않는 모드
    options.add_argument('--disable-gpu')          # GPU 비활성화 (윈도우용)
    options.add_argument('--no-sandbox')           # 권한 이슈 회피
    options.add_argument('--disable-dev-shm-usage')# 리소스 제한 회피
    # 필요시 윈도우 크기 지정
    options.add_argument('window-size=1920,1080')

    driver = webdriver.Chrome(options=options)
    driver.get(account_url)
    time.sleep(2)

    # 로그인 유도 팝업 닫기
    try:
        modal = WebDriverWait(driver,3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="dialog"]'))
        )
        btn = modal.find_element(By.XPATH, './/svg[@aria-label="닫기"]/..')
        driver.execute_script("arguments[0].click()", btn)
        time.sleep(1)
    except: pass

    thumbs = driver.find_elements(By.XPATH, '//a[contains(@href,"/p/")]')[:count]
    links  = [t.get_attribute("href") for t in thumbs]
    driver.quit()

    # Instaloader로 메타데이터 수집
    profile = instaloader.Profile.from_username(L.context, profile_name)
    posts = []
    for link in links:
        code = link.rstrip('/').split('/')[-1]
        post = instaloader.Post.from_shortcode(L.context, code)
        cap  = post.caption or ""
        hashtags = ", ".join(re.findall(r"#\w+", cap))
        words    = re.findall(r"[가-힣]{2,}", cap)
        keywords = ", ".join(w for w,_ in Counter(words).most_common(3))

        posts.append({
            "계정":        profile_name,
            "좋아요":      post.likes,
            "댓글":        post.comments,
            "날짜":        post.date_utc.date().isoformat(),
            "요일":        post.date_utc.strftime("%A"),
            "본문":        cap,
            "해시태그":     hashtags,
            "주요 키워드":  keywords,
            "URL":         link
        })

    # 요약 정보 + 게시물 테이블을 하나의 엑셀에 작성
    with pd.ExcelWriter(REPORT_PATH, engine='openpyxl') as W:
        # 1) 요약(팔로워·게시물 수)
        summary = pd.DataFrame([{
            "계정": profile_name,
            "팔로워 수": profile.followers,
            "게시물 수": profile.mediacount
        }])
        summary.to_excel(W, index=False, sheet_name="Sheet1", startrow=0)

        # 2) 게시물 상세 테이블 (두 줄 아래에)
        df = pd.DataFrame(posts)
        df.to_excel(W, index=False, sheet_name="Sheet1", startrow=3)

    return redirect(url_for('result'))

@app.route('/result', methods=['GET'])
def result():
    # 완료 페이지 렌더링
    return render_template("result.html")

@app.route('/download', methods=['GET'])
def download():
    return send_file(
        REPORT_PATH,
        as_attachment=True,
        download_name="인스타그램_분석결과.xlsx"
    )

@app.route('/analysis', methods=['GET'])
def analysis():
    return render_template('analysis.html')

@app.route('/analyze_result', methods=['POST'])
def analysis_result():
    # engagement calculate
    """
    https://www.thedigitalmkt.com/instagram-engagement-rate/#google_vignette
    engagement rate = (좋아요 + 댓글수) / 팔로워 수 x 100
    """
    import numpy as np
    from flask import flash

    posts = []
    followers = None

    # 파일 업로드 처리
    if 'file' in request.files and request.files['file'].filename != '':
        f = request.files['file']
        try:
            # 1. 팔로워 수 추출 (기존 시트 상단에서)
            df_head = pd.read_excel(f, nrows=2)
            followers = int(df_head['팔로워 수'].dropna().iloc[0])

            # 2. 게시물 데이터 추출 (5행부터 시작)
            df_posts = pd.read_excel(f, header=6)

            posts = []
            for i, row in df_posts.iterrows():
                if not pd.isna(row['좋아요']) and not pd.isna(row['댓글']):
                    posts.append(int(row['좋아요']) + int(row['댓글']))
            print(df_posts)
            print("✅ df.columns:", df_posts.columns.tolist())
            print("✅ followers:", followers)
            print("✅ posts:", posts)
        except Exception as e:
            flash(f"엑셀 처리 중 오류: {e}")
            return redirect(url_for('analysis'))

    # 수동 입력 처리
    else:
        try:
            followers = int(request.form.get('followers'))
            for i in range(10):
                likes = request.form.get(f'likes{i}')
                comments = request.form.get(f'comments{i}')
                if likes and comments:
                    posts.append(int(likes) + int(comments))
        except:
            flash("입력값 오류")
            return redirect(url_for('analysis'))

    if not followers or not posts:
        flash("데이터 부족")
        return redirect(url_for('analysis'))

    engagement_rates = [round(p / followers * 100, 2) for p in posts]
    average_er = round(np.mean(engagement_rates), 2)

    total_engagement = sum(posts)
    avg_engagement = total_engagement / len(posts)
    average_er = round(avg_engagement / followers * 100, 2)

    # 업계 기준 비교 함수
    def get_benchmark(f):
        if f < 2000: return 10.6
        elif f < 5000: return 6.1
        elif f < 10000: return 4.8
        elif f < 25000: return 3.7
        elif f < 50000: return 3.2
        elif f < 75000: return 2.5
        elif f < 250000: return 2.6
        elif f < 500000: return 2.8
        elif f < 1000000: return 2.2
        else: return 1.4

    benchmark = get_benchmark(followers)
    status = "✅ 업계 평균 이상" if average_er >= benchmark else "⚠️ 업계 평균보다 낮음"

    return render_template('result_analysis.html',
                           engagement_rates=engagement_rates,
                           average_er=average_er,
                           benchmark=benchmark,
                           status=status,
                           followers=followers)

if __name__ == "__main__":
    app.run(debug=True)
