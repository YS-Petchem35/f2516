import datetime as dt
import os

from korean_lunar_calendar import KoreanLunarCalendar
from lunar_python import Solar
from openai import OpenAI
import pandas as pd
import streamlit as st


STEMS = ["갑", "을", "병", "정", "무", "기", "경", "신", "임", "계"]
BRANCHES = ["자", "축", "인", "묘", "진", "사", "오", "미", "신", "유", "술", "해"]
ELEMENTS = ["목", "화", "토", "금", "수"]

CN_TO_KR_STEM = {
    "甲": "갑",
    "乙": "을",
    "丙": "병",
    "丁": "정",
    "戊": "무",
    "己": "기",
    "庚": "경",
    "辛": "신",
    "壬": "임",
    "癸": "계",
}
CN_TO_KR_BRANCH = {
    "子": "자",
    "丑": "축",
    "寅": "인",
    "卯": "묘",
    "辰": "진",
    "巳": "사",
    "午": "오",
    "未": "미",
    "申": "신",
    "酉": "유",
    "戌": "술",
    "亥": "해",
}

STEM_TO_ELEMENT = {
    "갑": "목",
    "을": "목",
    "병": "화",
    "정": "화",
    "무": "토",
    "기": "토",
    "경": "금",
    "신": "금",
    "임": "수",
    "계": "수",
}
BRANCH_TO_ELEMENT = {
    "자": "수",
    "축": "토",
    "인": "목",
    "묘": "목",
    "진": "토",
    "사": "화",
    "오": "화",
    "미": "토",
    "신": "금",
    "유": "금",
    "술": "토",
    "해": "수",
}

DEFAULT_FORM = {
    "name": "",
    "gender": "남성",
    "calendar_type": "양력",
    "birth_date": dt.date(1990, 1, 1),
    "is_leap_month": False,
    "birth_time_known": "알음",
    "birth_time": dt.time(12, 0),
    "occupation_interest": "직장/커리어",
    "question_input": "",
}


def initialize_form_state() -> None:
    for key, value in DEFAULT_FORM.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_basic_info() -> None:
    for key, value in DEFAULT_FORM.items():
        st.session_state[key] = value
    st.session_state.pop("latest_profile", None)
    st.session_state.pop("last_answer", None)


def apply_pending_reset() -> None:
    if st.session_state.pop("reset_requested", False):
        reset_basic_info()


def lunar_to_solar_date(lunar_date: dt.date, is_leap_month: bool) -> dt.date:
    cal = KoreanLunarCalendar()
    is_valid = cal.setLunarDate(
        lunar_date.year,
        lunar_date.month,
        lunar_date.day,
        isIntercalation=is_leap_month,
    )
    if not is_valid:
        raise ValueError("유효하지 않은 음력 날짜입니다.")
    return dt.datetime.strptime(cal.SolarIsoFormat(), "%Y-%m-%d").date()


def normalize_pillar_text(pillar: str) -> str:
    if len(pillar) < 2:
        return pillar
    stem = CN_TO_KR_STEM.get(pillar[0], pillar[0])
    branch = CN_TO_KR_BRANCH.get(pillar[1], pillar[1])
    return f"{stem}{branch}"


def compute_saju(solar_date: dt.date, birth_time: dt.time | None = None, time_known: bool = True) -> dict[str, str]:
    # lunar-python은 절기(24절기) 기반으로 팔자를 계산한다.
    # time_known이 False면 시주를 계산하지 않고 일주만 사용
    if birth_time is None:
        birth_time = dt.time(12, 0)
    
    solar = Solar.fromYmdHms(
        solar_date.year,
        solar_date.month,
        solar_date.day,
        birth_time.hour if time_known else 12,
        birth_time.minute if time_known else 0,
        0,
    )
    lunar = solar.getLunar()
    eight_char = lunar.getEightChar()

    year_text = normalize_pillar_text(eight_char.getYear())
    month_text = normalize_pillar_text(eight_char.getMonth())
    day_text = normalize_pillar_text(eight_char.getDay())
    hour_text = normalize_pillar_text(eight_char.getTime()) if time_known else "미상"

    return {
        "연주": year_text,
        "월주": month_text,
        "일주": day_text,
        "시주": hour_text,
        "연간": year_text[0],
        "월간": month_text[0],
        "일간": day_text[0],
        "시간": hour_text[0] if time_known else None,
        "time_known": time_known,
    }


def yin_yang_of_stem(stem: str) -> str:
    stem_idx = STEMS.index(stem)
    return "양" if stem_idx % 2 == 0 else "음"


def relation_group(day_element: str, target_element: str) -> str:
    generates = {"목": "화", "화": "토", "토": "금", "금": "수", "수": "목"}
    controls = {"목": "토", "토": "수", "수": "화", "화": "금", "금": "목"}
    if day_element == target_element:
        return "비겁"
    if generates[day_element] == target_element:
        return "식상"
    if controls[day_element] == target_element:
        return "재성"
    if generates[target_element] == day_element:
        return "인성"
    return "관성"


def ten_god_name(day_stem: str, target_stem: str) -> str:
    day_element = STEM_TO_ELEMENT[day_stem]
    target_element = STEM_TO_ELEMENT[target_stem]
    same_polarity = yin_yang_of_stem(day_stem) == yin_yang_of_stem(target_stem)
    group = relation_group(day_element, target_element)

    if group == "비겁":
        return "비견" if same_polarity else "겁재"
    if group == "식상":
        return "식신" if same_polarity else "상관"
    if group == "재성":
        return "편재" if same_polarity else "정재"
    if group == "관성":
        return "편관" if same_polarity else "정관"
    return "편인" if same_polarity else "정인"


def five_element_distribution(saju: dict[str, str]) -> dict[str, int]:
    dist = {element: 0 for element in ELEMENTS}
    pillars = ["연주", "월주", "일주"]
    if saju.get("time_known", True):
        pillars.append("시주")
    
    for key in pillars:
        pillar = saju[key]
        if pillar == "미상":
            continue
        stem = pillar[0]
        branch = pillar[1]
        dist[STEM_TO_ELEMENT[stem]] += 1
        dist[BRANCH_TO_ELEMENT[branch]] += 1
    return dist


def simple_gyeok(day_stem: str, month_branch: str) -> str:
    dm_element = STEM_TO_ELEMENT[day_stem]
    month_element = BRANCH_TO_ELEMENT[month_branch]
    group = relation_group(dm_element, month_element)
    mapping = {
        "비겁": "건록/비겁 성향",
        "식상": "식상격 성향",
        "재성": "재격 성향",
        "관성": "관격 성향",
        "인성": "인수격 성향",
    }
    return mapping[group]


def daewoon_direction(gender: str, year_stem: str) -> str:
    is_year_yang = yin_yang_of_stem(year_stem) == "양"
    if (gender == "남성" and is_year_yang) or (gender == "여성" and not is_year_yang):
        return "순행"
    return "역행"


def get_60_cycle_index(pillar: str) -> int:
    stem_idx = STEMS.index(pillar[0])
    branch_idx = BRANCHES.index(pillar[1])
    for idx in range(60):
        if idx % 10 == stem_idx and idx % 12 == branch_idx:
            return idx
    return 0


def shift_pillar(base_pillar: str, step: int) -> str:
    idx = get_60_cycle_index(base_pillar)
    moved = (idx + step) % 60
    return f"{STEMS[moved % 10]}{BRANCHES[moved % 12]}"


def build_daewoon(saju: dict[str, str], gender: str, birth_date: dt.date | None = None) -> list[tuple[str, str]]:
    direction = daewoon_direction(gender, saju["연간"])
    sign = 1 if direction == "순행" else -1
    
    # 절입 시각 기반 정밀 대운 시작 나이 계산
    if birth_date and saju.get("time_known", True):
        # 양주력 기준 월초(초하) 기준으로 대략 7-8세 사이에 시작
        base_start_age = 7
        day_of_month = birth_date.day
        # 음력 계산 시 초하(1-10일) 기준으로 미세 조정
        if day_of_month > 15:
            base_start_age = 8
        start_age = base_start_age
    else:
        # 시간을 모르면 정확한 계산이 어려우므로 7세로 고정
        start_age = 7
    
    rows: list[tuple[str, str]] = []
    for i in range(8):
        age_label = f"{start_age + i * 10}세"
        rows.append((age_label, shift_pillar(saju["월주"], sign * (i + 1))))
    return rows


def today_sewoon() -> str:
    today = dt.date.today()
    solar = Solar.fromYmdHms(today.year, today.month, today.day, 12, 0, 0)
    lunar = solar.getLunar()
    return normalize_pillar_text(lunar.getYearInGanZhiExact())


def calculate_age(birth_date: dt.date, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return max(age, 0)


def age_group(age: int) -> str:
    if age < 20:
        return "10대 이하"
    if age < 30:
        return "20대"
    if age < 40:
        return "30대"
    if age < 50:
        return "40대"
    if age < 60:
        return "50대"
    return "60대 이상"


def personality_bundle(
    name: str,
    gender: str,
    age: int,
    occupation_interest: str,
    saju: dict[str, str],
    elem_dist: dict[str, int],
) -> dict[str, str]:
    dominant = max(elem_dist, key=elem_dist.get)
    weakest = min(elem_dist, key=elem_dist.get)
    day_master = STEM_TO_ELEMENT[saju["일간"]]
    user_age_group = age_group(age)
    today_score = 60 + ((dt.date.today().toordinal() + sum(elem_dist.values()) + age) % 41)

    elem_explanation = {
        "목": "나무 기운 (성장, 확장, 창의성)",
        "화": "불 기운 (열정, 표현, 활동성)",
        "토": "흙 기운 (안정, 보살핌, 신뢰성)",
        "금": "금속 기운 (명확함, 분석, 질서)",
        "수": "물 기운 (지혜, 적응, 깊이)",
    }
    
    match_map = {
        "목": "성장지향형, 창의형",
        "화": "열정형, 표현형",
        "토": "안정형, 배려형",
        "금": "원칙형, 분석형",
        "수": "탐구형, 전략형",
    }
    caution_map = {
        "목": "성급한 확장",
        "화": "감정 과열",
        "토": "우유부단",
        "금": "지나친 비판",
        "수": "과도한 고민",
    }
    good_map = {
        "목": "새로운 공부/기획 시작",
        "화": "발표와 네트워킹",
        "토": "정리정돈과 루틴 관리",
        "금": "계약 검토와 문서 작업",
        "수": "리서치와 장기 전략 수립",
    }
    love_advice = {
        "목": "새로운 것을 시도하고 싶은 욕구가 강해요. 상대방의 페이스를 존중하면서 함께 성장하는 모습을 보여주면 좋아합니다.",
        "화": "표현력이 풍부하고 매력이 있어요. 감정을 솔직하게 드러내되, 때론 상대의 의견을 먼저 듣는 경청의 자세가 관계를 깊게 만듭니다.",
        "토": "믿을 수 있는 파트너로서의 신뢰성이 강점입니다. 안정적인 관계를 원하지만, 때론 주도적인 결정도 필요하니 용기를 내보세요.",
        "금": "원칙 있고 신중한 태도가 매력입니다. 논리적이지만 감정 표현을 조금 더 자연스럽게 해주면 상대방이 마음 문을 더 쉽게 열어요.",
        "수": "깊은 생각과 배려심이 있어요. 표현은 조용하지만 신뢰감이 깊으니, 차분한 대화를 통해 진정성을 드러내면 좋은 관계가 됩니다.",
    }
    work_advice = {
        "목": "새로운 프로젝트나 도전적인 환경에서 최고의 성과를 냅니다. 창의력을 마음껏 발휘할 수 있는 직무가 적합하며, 빠른 성장을 기대할 수 있어요.",
        "화": "소통과 표현이 핵심인 직무에 탁월합니다. 발표, 영업, 기획 등 사람들 앞에서 역할할 때 진가를 발휘하니, 이런 기회를 적극적으로 찾으세요.",
        "토": "꾸준함과 신뢰성으로 좋은 평가를 받습니다. 장기적인 프로젝트에 강하고, 팀의 안정제 역할을 하니 이 점을 인정받으면 좋아요.",
        "금": "체계적이고 분석적인 업무에 강합니다. 계획, 재무, 법무 등 정확성이 중요한 일에 만족도가 높으니, 이 분야에서 전문성을 키워보세요.",
        "수": "전략적 사고와 통찰력이 뛰어나요. 장기 계획 수립이나 컨설팅 같은 깊이 있는 업무에서 가치를 발휘할 수 있습니다.",
    }

    return {
        "성격": f"{name or '당신'}님은 일간(태어난 날의 천간) {saju['일간']}로, {elem_explanation[day_master]}를 타고났어요. {user_age_group} 나이대에는 {user_age_group} 특유의 변화 속에서 자신만의 길을 찾아가는 시기입니다. 현재 당신은 안정적이면서도 성장을 추구하는 균형 잡힌 성향을 보여주고 있습니다.",
        "잘 맞는 성격 유형": f"당신의 오행 분포를 보면 {dominant}가 가장 강합니다. 이는 {match_map[dominant]} 성향을 나타내요. 이런 분들과 함께 일하거나 관계하면 서로 시너지가 잘 나고, 부족한 부분을 자연스럽게 채울 수 있습니다.",
        "하면 좋은 것": f"지금 당신의 운의 흐름은 {good_map[dominant]}에 최적화되어 있어요. 이 시기에 이런 활동들을 하면 운이 가장 잘 펼쳐지니까, 가능한 한 이런 기회들을 적극적으로 만들어보세요. 작은 시작이라도 큰 결과로 이어질 수 있습니다.",
        "피해야할 것": f"약한 {weakest} 기운의 부족함을 억지로 채우려고 할 때 {caution_map[dominant]} 패턴이 생겨요. 예를 들어, 이 패턴에 빠지면 자꾸 반복된 실수가 늘어나요. 약점을 인정하고 천천히 습관을 고쳐나가는 게 가장 현명합니다.",
        "조심해야할 것": f"{gender}로서 당신의 강점은 큰 자산이에요. 하지만 대인관계에서는 상대의 말을 충분히 듣는 시간을 가져보세요. {caution_map[dominant]} 성향이 무의식중에 드러날 때, 상대방은 당신의 의도와 다르게 받아들일 수 있거든요.",
        "연애/대인운": love_advice[dominant],
        "재물/직업운": f"{occupation_interest} 분야에서 당신의 강한 {dominant} 기운을 활용하면 성과가 극대화돼요. {work_advice[dominant]} 당신의 약한 {weakest} 부분은 팀의 다른 사람들이나 멘토를 통해 보충하는 전략도 좋습니다.",
        "오늘의 운세": f"오늘의 운세 점수는 {today_score}점입니다. 점수가 높을수록 모든 일이 순조롭게 흐르는 날이에요. 중요한 결정은 오후 시간대에 충분히 생각한 후에 하고, 서두르지 않아도 될 일은 여유 있게 진행해도 좋습니다.",
    }


def answer_from_saju_rule(question: str, saju: dict[str, str], elem_dist: dict[str, int]) -> str:
    q = question.strip().lower()
    dominant = max(elem_dist, key=elem_dist.get)
    weakest = min(elem_dist, key=elem_dist.get)
    day_master = STEM_TO_ELEMENT[saju["일간"]]

    if not q:
        return "질문을 입력해 주세요. 사주 정보를 바탕으로 답변해드릴게요."
    if "연애" in q or "사랑" in q or "결혼" in q:
        return f"연애운은 속도 조절이 핵심입니다. 강한 {dominant} 기운은 매력이지만, {weakest} 보완을 위해 경청을 늘리면 관계가 좋아집니다."
    if "돈" in q or "재물" in q or "투자" in q:
        return f"재물운은 계획형 선택이 유리합니다. 일간 {saju['일간']}({day_master}) 기준으로 강한 {dominant} 영역에 집중해 보세요."
    if "직업" in q or "이직" in q or "취업" in q:
        return f"직업운은 강점 전개 시기입니다. {dominant} 기반 역량을 전면에 두고, {weakest} 보완 루틴을 함께 가져가면 좋습니다."
    if "건강" in q:
        return f"건강운은 리듬 관리가 우선입니다. 강한 {dominant} 기운으로 무리하지 말고 약한 {weakest} 보완 루틴을 유지하세요."
    return "질문 주제의 핵심은 균형입니다. 강점은 밀고 약점은 습관으로 보완하는 전략이 가장 안정적입니다."


def answer_with_llm(question: str, profile: dict[str, object], bundle: dict[str, str]) -> str:
    secret_key = ""
    try:
        secret_key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        secret_key = ""

    api_key = (
        st.session_state.get("openai_api_key")
        or os.getenv("OPENAI_API_KEY")
        or secret_key
    )
    if not api_key:
        return (
            "OPENAI_API_KEY가 없어 규칙형 답변으로 전환했습니다. "
            + answer_from_saju_rule(question, profile["saju"], profile["elements"])
        )

    client = OpenAI(api_key=api_key)
    
    # 오행 분포를 문자로 표현
    elem_str = ", ".join([f"{k}({v}개)" for k, v in profile['elements'].items()])
    time_note = "" if profile['saju'].get('time_known', True) else "(태어난 시간 미상 - 시주 미포함)"
    
    elem_descriptions = {
        "목": "나무(성장/창의/도전적)",
        "화": "불(열정/표현/활동적)",
        "토": "흙(안정/신뢰/보살핌)",
        "금": "금속(명확/분석/질서)",
        "수": "물(지혜/적응/깊이)"
    }
    dominant_elem = max(profile['elements'], key=profile['elements'].get)
    
    prompt = (
        "당신은 따뜻하고 실질적인 고양이 콘셉트의 사주 상담사입니다.\n"
        "사주는 어렵지 않습니다. 사용자가 비전문가여도 이해할 수 있도록 쉽고 친근하게 설명해주세요.\n"
        "사주팔자의 각 주(柱)는 연-월-일-시를 나타내고, 오행은 목화토금수의 5가지 에너지를 의미합니다.\n"
        "사용자의 구체적 상황과 질문에 직접 답변하되, 근거를 사주팔자에서 찾아 설명하세요.\n"
        "답변은 10~15문장의 길이로, 따뜻하고 희망적이면서도 실질적인 조언을 담아주세요.\n"
        "각 문장마다 '왜 그럴까?'에 대한 사주적 근거를 포함시키고, 구체적 실행 방안을 제시하세요.\n\n"
        f"[사용자 정보]\n"
        f"이름: {profile['name'] or '미입력'}\n"
        f"성별/나이: {profile['gender']} / {profile['age']}세\n"
        f"관심사/직업: {profile['occupation_interest']}\n\n"
        f"[사주팔자 설명]\n"
        f"연주(출생 연도): {profile['saju']['연주']} - 당신의 어린 시절/가족/근본 기질을 나타내요\n"
        f"월주(출생 월): {profile['saju']['월주']} - 당신의 사회적 활동/공적 이미지를 나타내요\n"
        f"일주(출생 일): {profile['saju']['일주']} - 당신 자신/본모습/중심을 나타내요\n"
        f"시주(출생 시): {profile['saju']['시주']}{time_note} - 당신의 노년/자식/정신세계를 나타내요\n"
        f"일간({saju['일간']})은 당신의 가장 중심적인 에너지입니다.\n\n"
        f"[오행 에너지 분포]\n"
        f"{elem_str}\n"
        f"당신은 {elem_descriptions[dominant_elem]} 에너지가 가장 강해요.\n"
        f"이것이 당신의 타고난 성향과 현재 운의 방향을 결정합니다.\n\n"
        f"[사용자의 기본 특성]\n"
    )
    for key, value in bundle.items():
        prompt += f"• {key}: {value}\n"
    
    prompt += f"\n[사용자 질문]\n'{question}'\n\n"
    prompt += (
        "위 사주 정보를 바탕으로 이 질문에 답해주세요.\n"
        "- 먼저 질문의 핵심을 사주와 연결시켜 설명하세요\n"
        "- 당신의 타고난 특성(오행)이 이 상황에서 어떻게 작용하는지 설명하세요\n"
        "- 현재 대운이나 세운이 이 일에 유리한지 말해주세요\n"
        "- 구체적이고 실현 가능한 조언을 3가지 이상 제시하세요\n"
        "- 마지막으로 희망적인 메시지로 마무리하세요"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 깊이 있으면서도 누구나 이해할 수 있게 설명하는 사주 상담사입니다. "
                    "사용자의 사주 정보와 질문을 정확히 이해하고, 구체적이고 실질적인 조언을 제공합니다. "
                    "항상 따뜻하고 희망적인 톤을 유지하세요."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        text = response.choices[0].message.content.strip()
        if not text:
            raise ValueError("empty response")
        return text
    except Exception:
        return (
            "LLM 응답 중 오류가 발생해 규칙형 답변으로 전환했습니다. "
            + answer_from_saju_rule(question, profile["saju"], profile["elements"])
        )


def render_theme() -> None:
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Gowun+Dodum&family=Gaegu:wght@400;700&display=swap');

            .stApp {
                background:
                    radial-gradient(circle at 5% 5%, rgba(147, 51, 234, 0.35), transparent 25%),
                    radial-gradient(circle at 95% 85%, rgba(88, 28, 135, 0.3), transparent 30%),
                    radial-gradient(circle at 50% 50%, rgba(59, 19, 97, 0.1), transparent 70%),
                    linear-gradient(135deg, #2d1b4e 0%, #1a0f2e 25%, #3d2463 50%, #2d1b4e 75%, #1f1235 100%);
                font-family: 'Gowun Dodum', serif;
                color: #e8deff;
            }

            h1, h2, h3 {
                font-family: 'Gaegu', cursive !important;
                letter-spacing: 0.02em;
                color: #d4a5ff;
                text-shadow: 0 2px 8px rgba(147, 51, 234, 0.3);
            }
            
            p {
                color: #d4a5ff;
            }

            .cat-hero {
                border-radius: 24px;
                padding: 22px;
                background: linear-gradient(135deg, rgba(200, 150, 255, 0.15) 0%, rgba(147, 51, 234, 0.1) 100%);
                border: 2px solid rgba(212, 165, 255, 0.4);
                box-shadow: 0 8px 32px rgba(88, 28, 135, 0.25), inset 0 1px 2px rgba(255, 255, 255, 0.1);
                margin-bottom: 16px;
                backdrop-filter: blur(10px);
            }
            
            .cat-hero p {
                margin: 8px 0 0 0;
                font-size: 0.95em;
                line-height: 1.6;
            }

            .fortune-card {
                border-radius: 18px;
                padding: 14px 16px;
                margin: 10px 0;
                background: linear-gradient(135deg, rgba(212, 165, 255, 0.12) 0%, rgba(147, 51, 234, 0.08) 100%);
                border-left: 5px solid #9333ea;
                box-shadow: 0 4px 16px rgba(88, 28, 135, 0.2);
                color: #d4a5ff;
                backdrop-filter: blur(8px);
                transition: all 0.3s ease;
            }
            
            .fortune-card:hover {
                box-shadow: 0 8px 24px rgba(147, 51, 234, 0.3);
                border-left-color: #d4a5ff;
                background: linear-gradient(135deg, rgba(212, 165, 255, 0.18) 0%, rgba(147, 51, 234, 0.12) 100%);
            }
            
            .fortune-card b {
                color: #f0d9ff;
                font-weight: 700;
            }
            
            .cat-background {
                position: fixed;
                opacity: 0.15;
                z-index: -1;
                pointer-events: none !important;
            }
            
            .cat-background-left {
                position: fixed;
                opacity: 0.08;
                z-index: -1;
                pointer-events: none !important;
                transform: scaleX(-1);
            }
            
            /* 폼 요소 스타일 */
            .stTextInput input,
            .stSelectbox select,
            .stDateInput input,
            .stTimeInput input,
            textarea {
                background-color: rgba(147, 51, 234, 0.1) !important;
                border: 1.5px solid rgba(212, 165, 255, 0.3) !important;
                color: #d4a5ff !important;
                border-radius: 12px !important;
                padding: 10px 12px !important;
            }
            
            .stTextInput input:focus,
            .stSelectbox select:focus,
            .stDateInput input:focus,
            .stTimeInput input:focus,
            textarea:focus {
                border-color: #9333ea !important;
                box-shadow: 0 0 12px rgba(147, 51, 234, 0.4) !important;
            }
            
            /* 라디오 버튼 */
            .stRadio label {
                color: #d4a5ff !important;
            }
            
            /* 체크박스 */
            .stCheckbox label {
                color: #d4a5ff !important;
            }
            
            /* 버튼 스타일 */
            .stButton > button {
                background: linear-gradient(135deg, #9333ea 0%, #7e22ce 100%);
                color: #fef0ff !important;
                border: none;
                border-radius: 12px;
                font-weight: 600;
                padding: 10px 20px;
                box-shadow: 0 4px 16px rgba(147, 51, 234, 0.4);
                transition: all 0.3s ease;
            }
            
            .stButton > button:hover {
                box-shadow: 0 6px 24px rgba(147, 51, 234, 0.6);
                transform: translateY(-2px);
                background: linear-gradient(135deg, #a855f7 0%, #9333ea 100%);
            }
            
            /* 알림창 */
            .stAlert {
                border-radius: 12px;
                background-color: rgba(147, 51, 234, 0.15);
                border: 1.5px solid rgba(212, 165, 255, 0.3);
                color: #d4a5ff;
            }
            
            /* 텍스트 색상 */
            .stMarkdown {
                color: #d4a5ff;
            }
            
            hr {
                border: none;
                border-top: 2px dashed rgba(147, 51, 234, 0.3);
                margin: 20px 0;
            }
        </style>
        
        <svg class="cat-background" width="200" height="200" viewBox="0 0 200 200" style="bottom: -60px; right: -80px;">
            <circle cx="100" cy="70" r="40" fill="%23000"/>
            <ellipse cx="100" cy="130" rx="50" ry="60" fill="%23000"/>
            <polygon points="70,20 60,0 80,15" fill="%23000"/>
            <polygon points="130,20 140,0 120,15" fill="%23000"/>
            <circle cx="85" cy="65" r="5" fill="%23ffeb3b"/>
            <circle cx="115" cy="65" r="5" fill="%23ffeb3b"/>
            <polygon points="100,80 95,90 105,90" fill="%23ffb6c1"/>
            <path d="M 100 95 Q 90 105 80 100" stroke="%23000" stroke-width="2" fill="none"/>
            <path d="M 50 140 Q 20 120 30 80" stroke="%23000" stroke-width="16" fill="none" stroke-linecap="round"/>
        </svg>
        
        <svg class="cat-background-left" width="200" height="200" viewBox="0 0 200 200" style="top: 100px; left: -100px;">
            <circle cx="100" cy="70" r="40" fill="%23000"/>
            <ellipse cx="100" cy="130" rx="50" ry="60" fill="%23000"/>
            <polygon points="70,20 60,0 80,15" fill="%23000"/>
            <polygon points="130,20 140,0 120,15" fill="%23000"/>
            <circle cx="85" cy="65" r="5" fill="%23ffeb3b"/>
            <circle cx="115" cy="65" r="5" fill="%23ffeb3b"/>
            <polygon points="100,80 95,90 105,90" fill="%23ffb6c1"/>
            <path d="M 100 95 Q 90 105 80 100" stroke="%23000" stroke-width="2" fill="none"/>
            <path d="M 50 140 Q 20 120 30 80" stroke="%23000" stroke-width="16" fill="none" stroke-linecap="round"/>
        </svg>
        """,
        unsafe_allow_html=True,
    )


def render_fortune_cards(bundle: dict[str, str]) -> None:
    for title, content in bundle.items():
        st.markdown(
            f"<div class='fortune-card'><b>{title}</b><br>{content}</div>",
            unsafe_allow_html=True,
        )


def save_chat_history(profile: dict[str, object], question: str, answer: str) -> None:
    """질문 답변 이력을 CSV 파일에 저장"""
    import csv
    from pathlib import Path
    
    history_file = Path("saju_chat_history.csv")
    timestamp = dt.datetime.now().isoformat()
    
    row = {
        "timestamp": timestamp,
        "name": profile.get("name", "미입력"),
        "gender": profile.get("gender", "미입력"),
        "age": profile.get("age", "미입력"),
        "occupation_interest": profile.get("occupation_interest", "미입력"),
        "saju": f"{profile['saju']['연주']}-{profile['saju']['월주']}-{profile['saju']['일주']}-{profile['saju']['시주']}",
        "question": question,
        "answer": answer,
    }
    
    try:
        if not history_file.exists():
            with open(history_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=row.keys())
                writer.writeheader()
                writer.writerow(row)
        else:
            with open(history_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=row.keys())
                writer.writerow(row)
    except Exception as e:
        st.warning(f"이력 저장에 실패했습니다: {str(e)}")


st.set_page_config(
    page_title="사주사주",
    page_icon="🐱",
    layout="centered",
)

initialize_form_state()
apply_pending_reset()
render_theme()

st.title("사주사주")
st.markdown(
    """
    <div class='cat-hero'>
        <h3>🐱 고양이 사주 연구소</h3>
        <p>✨ 신비로운 보랏빛 마력으로 당신의 사주팔자를 읽어주는 고양이입니다. ✨<br>생년월일과 태어난 시간을 입력하면 당신만의 운명을 해석해드립니다.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("LLM 설정 (선택)"):
    st.text_input(
        "OpenAI API Key",
        key="openai_api_key",
        type="password",
        placeholder="sk-...",
        help="입력하면 질문 답변이 LLM 기반으로 동작합니다.",
    )

# form 바깥에서 태어난 시간 여부 선택
st.subheader("기본 정보 입력")
name = st.text_input("이름", key="name", placeholder="홍길동")
gender = st.radio("성별", options=["남성", "여성"], key="gender", horizontal=True)
calendar_type = st.radio("달력 기준", options=["양력", "음력"], key="calendar_type", horizontal=True)
birth_date = st.date_input(
    "생년월일",
    key="birth_date",
    min_value=dt.date(1900, 1, 1),
    max_value=dt.date.today(),
)
is_leap_month = st.checkbox("윤달(음력인 경우만)", key="is_leap_month")

birth_time_known = st.radio(
    "태어난 시간",
    options=["알음", "모름"],
    key="birth_time_known",
    horizontal=True,
    help="태어난 정확한 시간을 알고 있으면 '알음', 모르면 '모름'을 선택하세요."
)

# 조건부 렌더링: "알음"일 때만 시간 입력 필드 표시
if birth_time_known == "알음":
    birth_time = st.time_input("태어난 시간(시:분)", key="birth_time", step=900)
else:
    birth_time = dt.time(12, 0)  # 기본값

occupation_interest = st.selectbox(
    "직업/관심사",
    options=["직장/커리어", "사업/창업", "학업/시험", "연애/결혼", "재테크/투자", "건강/라이프"],
    key="occupation_interest",
)

submitted = st.button("고양이에게 사주 물어보기")

if submitted:
    if not name:
        st.error("이름을 입력해주세요.")
    else:
        try:
            solar_date = (
                lunar_to_solar_date(birth_date, is_leap_month)
                if calendar_type == "음력"
                else birth_date
            )
            age = calculate_age(solar_date)
            time_known = st.session_state.get("birth_time_known", "알음") == "알음"
            saju = compute_saju(solar_date, birth_time, time_known=time_known)
            elem_dist = five_element_distribution(saju)

            ten_gods = {
                "연간": ten_god_name(saju["일간"], saju["연간"]),
                "월간": ten_god_name(saju["일간"], saju["월간"]),
            }
            if saju.get("시간"):
                ten_gods["시간"] = ten_god_name(saju["일간"], saju["시간"])
            
            simple_gyeok_text = simple_gyeok(saju["일간"], saju["월주"][1])
            daewoon_rows = build_daewoon(saju, gender, solar_date)
            fortune_bundle = personality_bundle(name, gender, age, occupation_interest, saju, elem_dist)

            st.session_state["latest_profile"] = {
                "name": name,
                "gender": gender,
                "calendar_type": calendar_type,
                "birth_date": birth_date,
                "birth_time": birth_time,
                "solar_date": solar_date,
                "age": age,
                "occupation_interest": occupation_interest,
                "saju": saju,
                "elements": elem_dist,
                "fortune_bundle": fortune_bundle,
            }

            st.success("사주 계산이 완료되었습니다.")
            st.write(f"- 이름: {name or '미입력'}")
            st.write(f"- 성별: {gender}")
            st.write(f"- 나이: {age}세")
            st.write(f"- 직업/관심사: {occupation_interest}")
            st.write(f"- 입력 생년월일({calendar_type}): {birth_date}")
            st.write(f"- 태어난 시간: {birth_time.strftime('%H:%M')}")
            st.write(f"- 계산 기준 양력일: {solar_date}")

            st.subheader("사주팔자")
            st.write(f"- 연주: {saju['연주']}")
            st.write(f"- 월주: {saju['월주']}")
            st.write(f"- 일주: {saju['일주']}")
            st.write(f"- 시주: {saju['시주']}")
            st.caption("절기 기준 계산은 lunar-python 라이브러리(절기 기반 팔자 계산)를 사용합니다.")

            st.subheader("오행 분포")
            elem_df = pd.DataFrame(
                {
                    "오행": list(elem_dist.keys()),
                    "개수": list(elem_dist.values()),
                }
            ).set_index("오행")
            st.bar_chart(elem_df)

            st.subheader("십신/격국 해석")
            st.write(f"- 연간 십신: {ten_gods['연간']}")
            st.write(f"- 월간 십신: {ten_gods['월간']}")
            if "시간" in ten_gods:
                st.write(f"- 시간 십신: {ten_gods['시간']}")
            st.write(f"- 격국 성향: {simple_gyeok_text}")

            st.subheader("대운/세운")
            st.write(f"- 대운 흐름: {daewoon_direction(gender, saju['연간'])}")
            st.write(f"- 올해 세운: {today_sewoon()}")
            st.table(pd.DataFrame(daewoon_rows, columns=["나이", "대운"]))

            st.subheader("고양이의 맞춤 조언")
            render_fortune_cards(fortune_bundle)
        except ValueError as error:
            st.error(str(error))
else:
    st.info("이름, 성별, 생년월일, 양력/음력, 태어난 시간, 관심사를 입력한 뒤 버튼을 눌러 주세요.")

if "latest_profile" in st.session_state:
    st.subheader("사주 질문하기")
    st.caption("입력한 사주 정보를 토대로 질문에 답변합니다. API 키가 있으면 LLM 답변, 없으면 규칙형 답변으로 동작합니다.")
    question = st.text_input("질문 입력", key="question_input", placeholder="예: 올해 이직 타이밍이 좋을까요?")
    if st.button("질문하기"):
        if not question.strip():
            st.warning("질문을 입력해주세요.")
        else:
            profile = st.session_state["latest_profile"]
            answer = answer_with_llm(question, profile, profile["fortune_bundle"])
            st.session_state["last_answer"] = answer
            # 이력 저장
            save_chat_history(profile, question, answer)
            st.success("질문과 답변이 저장되었습니다.")

if st.session_state.get("last_answer"):
    st.markdown(f"**고양이의 답변:** {st.session_state['last_answer']}")

st.markdown("---")
if st.button("기본 정보 초기화"):
    st.session_state["reset_requested"] = True
    st.rerun()
