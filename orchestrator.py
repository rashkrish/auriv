"""Orchestrator for the Personal Capability Agent.

Decides how each message is handled. Order of decisions:

1. Rephrase requests (the person pressed Not right or Confusing).
2. Emergency gate: fixed safe text, no model call.
3. Specific skills: scam check, action refusal, unclear request,
   stuck person, professional referral.
4. Default: explain.

Output gates run in code after the model replies. For example, every
scam reply must end with the official-channel line, even if the model
leaves it out.

Routing keywords are written for English and a few other languages.
Other languages reach the default route unless they contain an
emergency word, so check each language you offer before the demo.

Run this file on its own to check the English routing rules. No model calls are made.
    python orchestrator.py
"""

import json
import re
import time
from datetime import date, datetime, timedelta, timezone

import app as core

CFG = core.CFG

# ---------- Languages ----------

LANGUAGE_NAMES = {
    "en-GB": "English (UK)",
    "en-US": "English (US)",
    "en-IN": "English (India)",
    "fr-FR": "French",
    "de-DE": "German",
    "es-ES": "Spanish",
    "it-IT": "Italian",
    "nl-NL": "Dutch",
    "pl-PL": "Polish",
    "pt-BR": "Portuguese (Brazil)",
    "hi-IN": "Hindi",
    "bn-IN": "Bengali",
    "ta-IN": "Tamil",
    "ja-JP": "Japanese",
    "zh-CN": "Mandarin Chinese",
    "ko-KR": "Korean",
    "id-ID": "Indonesian",
    "vi-VN": "Vietnamese",
    "tr-TR": "Turkish",
    "sw-KE": "Swahili",
}
DEFAULT_LANGUAGE = "en-GB"

# ---------- Routing patterns ----------

EMERGENCY_RE = re.compile(
    r"\b(emergency(?! (fund|funds|savings|contact|contacts|kit|plan|exit|number for))|not breathing|chest pain|unconscious|bleeding (badly|heavily)"
    r"|suicid\w*|kill myself|overdose|someone is hurt|being attacked"
    r"|urgence|notfall|emergencia|emergenza|आपात\w*)\b",
    re.IGNORECASE,
)

# Words that do not work with \b word boundaries in Bengali and Chinese.
EMERGENCY_NATIVE_RE = re.compile(
    r"জরুরি|紧急|緊急|急救|응급|긴급|அவசர|darurat|khẩn cấp|noodgeval|nagły wypadek|emergência|acil durum|dharura",
    re.IGNORECASE,
)

SCAM_SIGNAL_RE = re.compile(
    r"(https?://|www\.|\bclick\b|\bverify\b|\bblocked\b|\bsuspended\b|\burgent(ly)?\b"
    r"|\bact now\b|\botp\b|\bpassword\b|\bgift cards?\b|\bpayment\b|\bfee\b|\bsecurity code\b"
    r"|\bpay\b[^.?!]{0,20}\bnow\b|\barrest\w*\b|\bkyc\b"
    r"|लिंक|क्लिक|ओटीपी|पासवर्ड|खाता बंद|अकाउंट बंद|ब्लॉक|गिरफ्तार|इनाम|लॉटरी|तुरंत भुगतान)",
    re.IGNORECASE,
)
RECEIVED_RE = re.compile(
    r"\b(received|got|this (text|message|email|call)|a (text|message|email|call))\b"
    r"|मैसेज आया|मेसेज आया|कॉल आया|फोन आया|ईमेल आया|एसएमएस आया|संदेश आया",
    re.IGNORECASE,
)
SCAM_INTENT_RE = re.compile(
    r"\b(check (this|it)|suspicious|scam|fake|is this (real|legit|safe)|warning)\b|फर्जी|फ़र्ज़ी|धोखा|ठगी|स्कैम",
    re.IGNORECASE,
)

ACTION_RE = re.compile(
    r"\b(pay|transfer|send|submit|log ?in|sign|book|cancel|buy|order)\b[^.?!]{0,60}\bfor me\b"
    r"|\bdo (this|it) for me\b",
    re.IGNORECASE,
)
OVERWHELM_RE = re.compile(
    r"\b(lots to do|too much|so much to do|overwhelm\w*|don'?t know where to start"
    r"|where do i start|where to start|feeling confused|feel confused|too many things|i feel stuck)\b"
    r"|बहुत (सारा|ज़्यादा|ज्यादा) काम|कहां से शुरू|कहाँ से शुरू|कुछ समझ नहीं आ रहा|बहुत परेशान",
    re.IGNORECASE,
)
VAGUE_RE = re.compile(
    r"^\s*(i\s+)?(don'?t|do not)\s+(understand|get it|know)\.?\s*$"
    r"|^\s*(what|huh|confused)\??\.?\s*$",
    re.IGNORECASE,
)
STUCK_RE = re.compile(
    r"\b(i'?m (stuck|lost)|i don'?t get (it|this)|i can'?t (do|figure) (it|this)|i'?m confused)\b",
    re.IGNORECASE,
)
PROFESSIONAL_RE = re.compile(
    r"\b(doctor|medicine|medication|symptom|fever|vet|pet|dog|cat|lawyer|legal|court"
    r"|tax|debt|loan|mortgage|eviction|evict\w*|landlord|tenan\w*|rent|diagnos\w*|prescription"
    r"|headaches?|pain|aches?|rash|cough\w*|vomit\w*|dizz\w*|injur\w*|sore|swollen|bleeding|nhs|gp)\b"
    r"|डॉक्टर|दवा|दवाई|बुखार|दर्द|खांसी|उल्टी|चक्कर|वकील|कर्ज|क़र्ज़|लोन|मकान मालिक|किराया",
    re.IGNORECASE,
)

CURRENT_RE = re.compile(r"\b(latest|current|today|right now|this week)\b", re.IGNORECASE)

PLANNING_RE = re.compile(
    r"\b(organi[sz]\w*|plan|plans|planning|schedule|prioriti[sz]\w*)\b"
    r"|\bmy (meetings|assignments|tasks|deadlines)\b",
    re.IGNORECASE,
)

# Several meetings, classes or deadlines to fit together: organise a real schedule.
_SCHED_PLURAL = r"(meetings|classes|lectures|lessons|appointments|shifts|deadlines|assignments|exams)"
SCHEDULE_RE = re.compile(
    r"\b(a lot of|lots of|loads of|many|several|too many|so many|all (of )?my|my)\s+(\w+\s+){0,2}" + _SCHED_PLURAL + r"\b"
    r"|\b(organi[sz]\w*|plan|planning|sort out|manage|arrange|fit in|juggle|juggling)\b[^.?!]{0,60}\b"
    r"(" + _SCHED_PLURAL[1:-1] + r"|timetable|calendar|schedule)\b"
    r"|\b(my (schedule|timetable|calendar))\b|\b(plan|organi[sz]e) my (week|day)\b"
    r"|(बहुत सारी|कई|मेरी) .{0,15}(मीटिंग्स|मीटिंग|क्लासेस|कक्षाएं|अपॉइंटमेंट)|शेड्यूल|टाइमटेबल|समय सारणी",
    re.IGNORECASE,
)

# Several dates or deadlines in one message: treat it as a schedule to plan.
DATE_WORD_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|next week|this week|weekend"
    r"|deadlines?|due|(after|in|within) (\d+|a|one|two|three|four|five|six|seven) (days?|weeks?)"
    r"|\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*)\b",
    re.IGNORECASE,
)

# "I want to work on / learn / build X" with a time frame: a goal to plan with real dates.
GOAL_INTENT_RE = re.compile(
    r"\b(i want to (work on|learn|build|make|finish|complete|start|prepare|save|pass|improve|get fit|read|practi[cs]e|get better at|get ready)|i (need|have) to (practi[cs]e|get ready)|i'?m saving|i need to (finish|complete|prepare|learn|build)|my goal is|i'?m planning to)\b"
    r"|मुझे .{0,60}(सीखना|सीखनी|बनाना|पूरा करना|पूरी करनी|तैयारी करनी|तैयारी करना|प्रैक्टिस करनी|प्रैक्टिस करना|अभ्यास करना|करना|करनी) है|मेरा लक्ष्य"
    r"|\bmujhe\b.{0,60}\b(seekhna|sikhna|seekhni|sikhni|karna|karni|tayari|taiyari|practice|banana|poora|pura)\b.{0,15}\b(hai|h)\b",
    re.IGNORECASE)
GOAL_WORD_RE = re.compile(
    r"\b(a goal|my goal|the goal|new goal|goal is|goals for|start a goal|set a goal|work(ing)? (on|toward|towards) (a |my )?(goal|target)"
    r"|work(ing)? towards?|my target|target is|resolution|i want to (lose|gain|get fit|run|read|save up|become|reach|achieve)"
    r"|i (have|need) to (prepare|study|revise|finish|complete) for)\b"
    r"|लक्ष्य|मकसद|गोल पर|un objectif|mon objectif|mi meta|mi objetivo|mein ziel|il mio obiettivo|mijn doel|mój cel|minha meta|meu objetivo"
    r"|tujuan saya|mục tiêu|hedefim|lengo langu|目標|目标|목표|லக்ஷ்யம்|இலக்கு|লক্ষ্য",
    re.IGNORECASE)
# Questions about a word ("what is a goal in football?") are not goals to plan.
QUESTION_START_RE = re.compile(r"^\s*(what|who|which|when|why|how many|define|meaning of|क्या होता|क्या है)\b", re.IGNORECASE)
TIMEFRAME_RE = re.compile(
    r"\b(this|one|a|next|in|within|by|for) (week|month|fortnight)\b|\b(on|by|before|until) (this |next )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b(on|by|before) (the )?\d{1,2}(st|nd|rd|th)?( of)? (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b|\btomorrow\b|\b\d+ (days?|weeks?|months?)\b|\bdeadline\b|\bby (monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b"
    r"|हफ्ते|हफ़्ते|सप्ताह|महीने|दिनों में|डेडलाइन|कल तक|परसों"
    r"|\b(agle|is) (hafte|hafta|mahine|saal)\b|\b\d+\s*(din|hafte|hafton|mahine)\b|\bkal tak\b",
    re.IGNORECASE)

# "Teach me", "can you teach me", "सिखा सकती हो": the learning coach starts a lesson.
TEACH_RE = re.compile(
    r"\b(teach me|can you teach|could you teach|will you teach|help me (to )?(learn|practi[sc]e)|give me (a )?lesson|i want lessons?)\b"
    r"|सिखा|सिखाओ|सिखाइए|सिखाएं|सिखाएँ|পড়াও|শেখাও|শেখান|கற்றுக்கொடு|கற்றுத்|apprends-moi|peux-tu m'apprendre|bring mir|beibringen"
    r"|enséñame|me enseñas|insegnami|mi insegni|ensina-me|me ensina|me ensine|leer me|naucz mnie|ajari saya|ajarkan|dạy tôi|bana öğret|nifundishe"
    r"|教えて|教我|가르쳐",
    re.IGNORECASE)

# Hands-on skills: Auriv cannot watch technique, so it teaches the basics and points to good videos and coaches.
HANDS_ON_RE = re.compile(
    r"\b(badminton|tennis|table tennis|cricket|football|soccer|basketball|volleyball|swimming|swim|cycling|ride a bike|running|yoga|gym"
    r"|workout|exercise|stretch\w*|dance|dancing|guitar|piano|keyboard|violin|tabla|drums|singing|sing|drawing|painting|sketching"
    r"|cooking|cook|baking|bake|knitting|sewing|stitching|gardening|driving|drive a car|skating|martial arts|karate|boxing|chess)\b"
    r"|बैडमिंटन|क्रिकेट|फुटबॉल|तैराकी|तैरना|साइकिल|योग|व्यायाम|नृत्य|डांस|गिटार|हारमोनियम|तबला|गाना गाना|चित्र बनाना|पेंटिंग"
    r"|खाना बनाना|सिलाई|बुनाई|बागवानी|गाड़ी चलाना|कार चलाना|শরীরচর্চা|সাঁতার|রান্না|நீச்சல்|சமையல்|யோகா"
    r"|natation|cuisine|schwimmen|kochen|natación|cocinar|nuoto|cucinare|natação|cozinhar|zwemmen|pływanie|水泳|料理|游泳|做饭|수영|요리"
    r"|berenang|memasak|bơi|nấu ăn|yüzme|yemek yapmak|kuogelea|kupika",
    re.IGNORECASE)

# Licences, permits and tests are official matters even when the topic is a hands-on skill like driving.
LICENCE_RE = re.compile(r"\b(licen[cs]e|permit|documents?|apply|application|test centre|theory test|fine|penalty)\b"
                        r"|लाइसेंस|दस्तावेज|कागजात|आवेदन", re.IGNORECASE)

# Cooking: a recipe can be given fully in words, so Auriv gives it directly; recipe pages and videos are extras.
COOKING_RE = re.compile(
    r"\b(recipes?|cook\w*|bak(e|ing)|how (do i|to) make (a |an |some )?(dal|daal|rice|curry|cake|bread|pasta|roti|chapati|paneer|biryani|soup|omelette|eggs?|tea|chai|pancakes?|salad|sauce|cookies|pizza|noodles|khichdi|halwa|kheer|sambar|dosa|idli|upma|poha))\b"
    r"|रेसिपी|विधि|खाना बनाना|पकाना|पकाएं|(दाल|चावल|रोटी|पराठा|पनीर|बिरयानी|खीर|हलवा|सब्ज़ी|सब्जी|चाय|केक|खिचड़ी|पोहा|उपमा|डोसा|इडली|सांभर|अंडा|ऑमलेट).{0,20}(कैसे बना|बनाने|बनाएं|बनाऊं|बनाते)"
    r"|রান্না|রেসিপি|சமையல்|செய்முறை|recette|rezept|receta|ricetta|receita|recept|przepis|レシピ|料理|食谱|做饭|요리|레시피|resep|memasak|công thức|nấu|tarif|yemek|mapishi|kupika",
    re.IGNORECASE)

# "I want to learn Hindi" without a time frame: start a lesson (with a time frame it is a goal to plan).
WANT_LEARN_RE = re.compile(
    r"\b(i want to learn|i'?d like to learn|i wanna learn|i would like to learn|i want to practi[sc]e|how (can|do) i learn)\b"
    r"|सीखना (है|चाहती|चाहता)|सीखना चाहूँगी|सीखना चाहूंगी|(प्रैक्टिस|अभ्यास) (करनी|करना) है|\b(seekhna|sikhna) (hai|chahti|chahta)\b|\bpractice karni hai\b|apprendre le|ich möchte .{0,20} lernen|quiero aprender|voglio imparare|quero aprender"
    r"|ingin belajar|muốn học|öğrenmek istiyorum|nataka kujifunza|学びたい|想学|배우고 싶",
    re.IGNORECASE)

# "Help me write an email / letter / message": a draft to copy, not advice about the problem.
WRITE_RE = re.compile(
    r"\b(help me (to )?(write|draft)|write (me )?an? (email|e-mail|letter|message|text|note|complaint|reply|application|cv|cover letter)"
    r"|draft (an? )?(email|letter|message|reply)|write a polite|write to my)\b"
    r"|(ईमेल|पत्र|चिट्ठी|मैसेज|आवेदन|एप्लीकेशन).{0,25}(लिखने|लिखो|लिख दो|लिखें|लिखना)|aide-moi à écrire|écris un|ayúdame a escribir|escribe un",
    re.IGNORECASE)

# Skills that carry on across turns: a short follow-up (like a list of times) stays in the same skill.
CONTINUING_SKILLS = {"schedule", "goal_planner", "guide_step", "task_helper", "learning_coach"}

# ---------- Reply quality checks (run in code, after the model replies) ----------

# Notes about how to answer must never reach the person. These replies are always rejected.
META_RE = re.compile(
    r"\bthe user (wants|asked|is asking|said|needs|has)\b|\bas an ai\b"
    r"|\bi (need|should) to (respond|answer|reply|write)\b|\blet me (think|analy[sz]e|draft)\b"
    r"|\bthe (response|reply|answer) should\b|\bdraft (response|reply)\b|^\s*final answer\s*:"
    r"|\b(is|are) wrapped (so|for|in)\b|\bso the app can (read|say|speak)\b|\{\{\s*\.\.\s*\}\}"
    r"|^\W*you'?re right\W+i should(n'?t| not)\b",
    re.IGNORECASE | re.MULTILINE,
)
CANT_SAVE_RE = re.compile(r"\bi (can'?t|cannot|am unable to|'m unable to|don'?t have the ability to) (save|store|remember|keep track)", re.IGNORECASE)
VAGUE_Q_RE = re.compile(r"what would need to happen|how does that make you feel|what'?s on your mind|what is on your mind", re.IGNORECASE)
# The model describing itself instead of answering ("I'm a language model built by NVIDIA researchers").
IDENTITY_RE = re.compile(
    r"\b(i am|i'm) (just )?(an? )?(ai |large )?(language model|llm)\b|\b(built|created|made|developed) by nvidia\b|nvidia researchers"
    r"|\b(i am|i'm|my name is) nemotron\b|नेमोट्रॉन|नेमोट्रोन"
    r"|भाषा मॉडल|लैंग्वेज मॉडल|एनवीआईडिया|एनवीडिया|modèle de langage|sprachmodell|modelo de lenguaje|modello linguistico"
    r"|modelo de linguagem|言語モデル|语言模型|언어 모델|model bahasa|mô hình ngôn ngữ|dil modeli",
    re.IGNORECASE)
IDENTITY_ASKED_RE = re.compile(r"\b(who|what) are you\b|\bwho (made|built|created) you\b|\bare you (an? )?(ai|bot|robot|human)\b"
                               r"|तुम कौन|आप कौन|किसने बनाया|क्या तुम (ai|एआई)", re.IGNORECASE)
# Facts that changed after the models were trained. Each was checked on an official page; add new ones the same way.
FACT_UPDATES = [
    ("GB", re.compile(r"\b(evict\w*|section 21|section 8|notice to (quit|leave)|landlord wants me (out|to leave)|kick(ed|ing)? me out)\b|wants me out", re.IGNORECASE),
     "In England, Section 21 'no-fault' evictions were abolished on 1 May 2026 (Renters' Rights Act 2025). A landlord now needs a "
     "legal reason (a possession ground, such as rent arrears or selling the home) and a court order; a tenant does not have to leave "
     "just because of a notice. Section 21 notices served on or before 30 April 2026 may still be used in court until 31 July 2026. "
     "Never tell the person a landlord can give a Section 21 notice now. (Checked 2026-10-29: housinghub.campaign.gov.uk)"),
]

# "Who are you / who made you": answered with fixed text in the person's language.
IDENTITY_ONLY_RE = re.compile(
    r"^\W*((hi|hello|hey)\W+)?(auriv\W+)?(who|what) are you\W*$|\bwho (made|built|created|designed) you\b|\bare you (an? )?(ai|bot|robot|human|real person)\b"
    r"|तुम कौन हो|आप कौन हैं|आप कौन हो|(तुम्हें|आपको|तुमको) किसने बनाया|qui t'a (créé|fait)|qui es-tu|quién te (creó|hizo)|quién eres"
    r"|wer hat dich|wer bist du|chi ti ha creato|chi sei|quem te criou|quem é você|siapa yang membuat(mu| kamu)|siapa kamu|誰が作|あなたは誰",
    re.IGNORECASE)
IDENTITY_TEXTS = {
    "en": "I'm Auriv, your guide: an AI assistant for everyday tasks, learning and staying safe. I was made by Rashmi Sarwal, "
          "and I run on NVIDIA Nemotron models, served through Nebius. What would you like help with?",
    "hi": "मैं Auriv हूँ, आपकी गाइड: रोज़मर्रा के काम, नई चीज़ें सीखने और सुरक्षित रहने में मदद करने वाली AI सहायक। "
          "मुझे रश्मि सरवाल ने बनाया है, और मैं NVIDIA Nemotron मॉडल पर चलती हूँ, जो Nebius पर चलते हैं। बताइए, मैं आपकी क्या मदद करूँ?",
    "es": "Soy Auriv, tu guía: una asistente de IA para tareas diarias, aprender y estar a salvo. Me creó Rashmi Sarwal "
          "y funciono con modelos NVIDIA Nemotron, a través de Nebius. ¿En qué te ayudo?",
    "fr": "Je suis Auriv, votre guide : une assistante IA pour les tâches du quotidien, apprendre et rester en sécurité. "
          "J'ai été créée par Rashmi Sarwal et je fonctionne avec les modèles NVIDIA Nemotron, via Nebius. Comment puis-je vous aider ?",
    "de": "Ich bin Auriv, Ihre Begleiterin: eine KI-Assistentin für Alltagsaufgaben, Lernen und Sicherheit. Rashmi Sarwal hat mich "
          "entwickelt, und ich laufe mit NVIDIA-Nemotron-Modellen über Nebius. Wobei kann ich helfen?",
    "it": "Sono Auriv, la tua guida: un'assistente IA per le attività quotidiane, per imparare e restare al sicuro. Mi ha creata "
          "Rashmi Sarwal e funziono con i modelli NVIDIA Nemotron, tramite Nebius. Come posso aiutarti?",
    "pt": "Sou a Auriv, sua guia: uma assistente de IA para tarefas do dia a dia, aprender e ficar em segurança. Fui criada por "
          "Rashmi Sarwal e funciono com modelos NVIDIA Nemotron, pela Nebius. Como posso ajudar?",
    "id": "Saya Auriv, pemandu Anda: asisten AI untuk tugas sehari-hari, belajar, dan tetap aman. Saya dibuat oleh Rashmi Sarwal "
          "dan berjalan dengan model NVIDIA Nemotron melalui Nebius. Ada yang bisa saya bantu?",
    "ja": "私はAuriv（オーリヴ）、あなたのガイドです。毎日の用事、学び、安全のためのAIアシスタントです。Rashmi Sarwalが作り、"
          "NebiusのNVIDIA Nemotronモデルで動いています。何をお手伝いしましょうか？",
}

# Who made Auriv: never "NVIDIA researchers", in any language.
WRONG_MAKER_RE = re.compile(
    r"nvidia researchers|\b(created|made|built|developed|trained) by (the )?(nvidia|openai|google|meta)\b"
    r"|(NVIDIA|एनवीआईडिया|एनवीडिया) के (शोधकर्ता|रिसर्चर)|शोधकर्ताओं द्वारा (प्रशिक्षित|बनाया|विकसित)|(NVIDIA|एनवीआईडिया|एनवीडिया) (द्वारा|ने) (बनाया|प्रशिक्षित|विकसित)"
    r"|(एक )?भाषा मॉडल हूँ|language model (developed|made|built|created|trained)",
    re.IGNORECASE)
# A real refusal to teach ("No, I can't teach..."), not an honest limit inside a lesson ("मैं आपको देख नहीं सकती, इसलिए...").
TEACH_REFUSAL_RE = re.compile(
    r"^[\s*_\W]*(no[,.!]|sorry,? i can'?t|i('m| am) (sorry|unable)|i can(no|')t (teach|help)|नहीं[,।]|माफ़ कीजिए|माफ करें|क्षमा करें)"
    r"|(सिखा|पढ़ा) नहीं (सकती|सकता)|can'?t teach|cannot teach", re.IGNORECASE)
IDENTITY_FACTS = ("Facts about you: you are Auriv, a personal guide for everyday tasks, learning and staying safe, made by Rashmi Sarwal. "
                  "You run on NVIDIA Nemotron models, served through Nebius. Say this in one or two sentences, in the person's language, "
                  "then offer help with one example.")
IDENTITY_FIX = ("You are Auriv, a kind everyday guide. Do not describe yourself as a language model, and never use a model or product name "
                "such as Nemotron in your reply or in practice phrases. Answer the person's request directly. If you are teaching, "
                "use the learner's name or an example name like Asha.")
# A practice attempt the app's speech check marked ✓ was correct: the reply must not invent a fix or sound advice.
INVENTED_FIX_RE = re.compile(
    r"one thing to (fix|improve|work on)|to fix:|pronunciation tip|nasal|pause (after|before)|rhythm|longer .{0,10}sound|more length"
    r"|सुधार|उच्चारण|correction|à corriger|corrige|zu verbessern|aussprache|para corregir|pronunciación|da correggere|pronuncia",
    re.IGNORECASE)
CORRECT_ATTEMPT_FIX = ("The person's attempt was correct (the app's speech check matched it). Say so in one warm line and move on to the "
                       "next new phrase with a new tiny practice. Do not suggest any fix or pronunciation advice.")
SUBSTANTIVE_SKILLS = {"schedule", "goal_planner", "research", "task_helper", "learning_coach", "guide_step"}


def quality_problem(answer, skill, user_message=""):
    """Return (strict, correction) for a reply that should not be shown, or (False, None) if it is fine."""
    if WRONG_MAKER_RE.search(answer):
        return True, IDENTITY_FIX + " " + IDENTITY_FACTS
    if IDENTITY_RE.search(answer) and not IDENTITY_ASKED_RE.search(user_message or ""):
        return True, IDENTITY_FIX
    if skill == "learning_coach" and TEACH_REFUSAL_RE.search(answer[:80]):
        return True, ("You can teach this. Say yes in one short line and start Lesson 1 now, "
                      "following the lesson format. Do not talk about yourself.")
    if META_RE.search(answer):
        return True, "Your reply included notes about how to answer. Reply again with only the answer for the person."
    if (user_message or "").rstrip().endswith("✓") and INVENTED_FIX_RE.search(answer):
        return False, CORRECT_ATTEMPT_FIX
    if CANT_SAVE_RE.search(answer):
        return False, ("Do not say you cannot save or remember. The app has a save button under your reply; "
                       "if the person wants to keep this, tell them to tap it, in their language.")
    if VAGUE_Q_RE.search(answer):
        return False, "Replace the vague question with one specific, practical next action."
    if skill == "schedule" and TIME_GIVEN_RE.search(user_message or "") and "|" not in answer:
        return False, ("Put the schedule in one table with the columns Day | Time | What | Notes (a header row, then one row per item, "
                       "earliest first), then the clashes and suggestions below it.")
    if skill in SUBSTANTIVE_SKILLS and len(answer.split()) < 15:
        return False, "Your reply was too thin. Give a concrete, useful answer the person can act on now."
    return False, None

# ---------- Fixed text, by language prefix (en, fr, de, es, hi) ----------

EMERGENCY_TEXTS = {
    "tr": "Bu bir acil durum gibi görünüyor. Lütfen hemen ülkenizin acil durum numarasını arayın. Yanınızda biri varsa çağrıyı yapmanıza yardım etmesini isteyin. Kendinize zarar vermeyi düşünüyorsanız, hemen yakınınızdaki birine söyleyin ve ülkenizdeki bir kriz hattına ulaşın.",
    "sw": "Hii inaonekana kuwa dharura. Tafadhali piga sasa namba ya dharura ya nchi yako. Ikiwa kuna mtu karibu nawe, mwombe akusaidie kupiga simu. Ukifikiria kujiumiza, mwambie mtu aliye karibu mara moja na wasiliana na huduma ya msaada wa dharura nchini kwako.",
    "it": "Sembra un'emergenza. Chiama subito il numero di emergenza del tuo paese. Se c'è qualcuno con te, chiedigli di aiutarti a fare la chiamata. Se stai pensando di farti del male, parlane subito con qualcuno vicino a te e contatta una linea di crisi del tuo paese.",
    "nl": "Dit lijkt een noodgeval. Bel nu het alarmnummer van je land. Als er iemand bij je is, vraag die persoon je te helpen met bellen. Als je eraan denkt jezelf pijn te doen, praat er meteen met iemand in de buurt over en neem contact op met een crisislijn in je land.",
    "pl": "To wygląda na nagły przypadek. Zadzwoń teraz na numer alarmowy swojego kraju. Jeśli ktoś jest przy tobie, poproś go o pomoc w połączeniu. Jeśli myślisz o zrobieniu sobie krzywdy, od razu powiedz o tym komuś w pobliżu i skontaktuj się z telefonem kryzysowym w swoim kraju.",
    "pt": "Isto parece ser uma emergência. Ligue agora para o número de emergência do seu país. Se houver alguém com você, peça que ajude a fazer a ligação. Se estiver pensando em se machucar, fale imediatamente com alguém por perto e entre em contato com uma linha de crise do seu país.",
    "ta": "இது அவசரநிலையாக இருக்கலாம். உங்கள் நாட்டின் அவசர எண்ணை உடனடியாக அழையுங்கள். உங்களுடன் யாராவது இருந்தால், அழைப்பதற்கு உதவச் சொல்லுங்கள். உங்களைத் தீங்கு செய்துகொள்ள நினைத்தால், உடனே அருகில் உள்ள ஒருவரிடம் சொல்லுங்கள், உங்கள் நாட்டின் நெருக்கடி உதவி எண்ணையும் தொடர்பு கொள்ளுங்கள்.",
    "ja": "緊急事態のようです。今すぐお住まいの国の緊急番号に電話してください。近くに人がいれば、電話をかけるのを手伝ってもらってください。自分を傷つけることを考えている場合は、すぐに近くの人に伝え、お住まいの国の相談窓口に連絡してください。",
    "ko": "응급 상황으로 보입니다. 지금 바로 우리나라의 응급 번호로 전화하세요. 곁에 누군가 있다면 전화를 도와 달라고 하세요. 스스로를 해치는 생각이 든다면 지금 바로 주변 사람에게 말하고, 우리나라의 위기 상담 전화에 연락하세요.",
    "id": "Ini tampaknya keadaan darurat. Segera hubungi nomor darurat di negara Anda. Jika ada orang di dekat Anda, minta bantuan mereka untuk menelepon. Jika Anda berpikir untuk menyakiti diri sendiri, segera beri tahu orang terdekat dan hubungi layanan krisis di negara Anda.",
    "vi": "Đây có vẻ là trường hợp khẩn cấp. Hãy gọi ngay số khẩn cấp của quốc gia bạn. Nếu có người bên cạnh, hãy nhờ họ giúp bạn gọi. Nếu bạn đang nghĩ đến việc tự làm hại bản thân, hãy nói ngay với người xung quanh và liên hệ đường dây hỗ trợ khủng hoảng ở quốc gia bạn.",
    "bn": "এটি জরুরি অবস্থা বলে মনে হচ্ছে। এখনই আপনার দেশের জরুরি নম্বরে কল করুন। আপনার সাথে কেউ থাকলে তাকে কল করতে সাহায্য করতে বলুন। আপনি যদি নিজেকে আঘাত করার কথা ভাবেন, তাহলে এখনই কাছের কাউকে বলুন এবং আপনার দেশের কোনো সংকট হেল্পলাইনে যোগাযোগ করুন।",
    "zh": "这看起来可能是紧急情况。请立即拨打您所在国家的紧急电话。如果身边有人，请他帮您拨打。如果您有伤害自己的想法，请立即告诉身边的人，并联系您所在国家的危机求助热线。",
    "en": (
        "This sounds like it could be an emergency. Please call your local emergency number now. "
        "If someone is with you, ask them to help you make the call. "
        "If you are thinking about harming yourself, tell someone near you right away "
        "and contact a crisis line in your country."
    ),
    "fr": (
        "Cela semble être une urgence. Appelez tout de suite le numéro d'urgence de votre pays. "
        "Si quelqu'un est avec vous, demandez-lui de vous aider à appeler. "
        "Si vous pensez à vous faire du mal, parlez-en tout de suite à une personne près de vous "
        "et contactez une ligne d'écoute de crise dans votre pays."
    ),
    "de": (
        "Das klingt nach einem Notfall. Bitte rufen Sie jetzt die Notrufnummer Ihres Landes an. "
        "Wenn jemand bei Ihnen ist, bitten Sie ihn, Ihnen beim Anruf zu helfen. "
        "Wenn Sie daran denken, sich selbst zu verletzen, sprechen Sie sofort mit einer Person in Ihrer Nähe "
        "und wenden Sie sich an eine Krisenhotline in Ihrem Land."
    ),
    "es": (
        "Esto parece una emergencia. Por favor, llame ahora al número de emergencias de su país. "
        "Si hay alguien con usted, pídale que le ayude a hacer la llamada. "
        "Si está pensando en hacerse daño, hable de inmediato con alguien cerca de usted "
        "y contacte a una línea de crisis de su país."
    ),
    "hi": (
        "यह आपातकालीन स्थिति लग रही है। कृपया अभी अपने देश के आपातकालीन नंबर पर कॉल करें। "
        "अगर आपके साथ कोई है, तो उनसे कॉल करने में मदद माँगें। "
        "अगर आप खुद को नुकसान पहुँचाने के बारे में सोच रहे हैं, तो अभी अपने आसपास किसी व्यक्ति से बात करें "
        "और अपने देश की किसी क्राइसिस हेल्पलाइन से संपर्क करें।"
    ),
}

OFFICIAL_LINES = {
    "tr": "Herhangi bir işlem yapmadan önce kartınızdaki resmi numarayla veya bankanın resmi web sitesinden kontrol edin, mesajdaki bağlantı ya da numarayla değil.",
    "sw": "Kabla ya kufanya lolote, hakiki kwa kutumia namba rasmi iliyo kwenye kadi yako au tovuti rasmi ya benki, si kwa kiungo au namba iliyo kwenye ujumbe.",
    "it": "Prima di fare qualsiasi cosa, verifica con il numero ufficiale sulla tua carta o sul sito ufficiale della banca, non con un link o un numero presente nel messaggio.",
    "nl": "Controleer voordat je iets doet het officiële nummer op je pas of de officiële website van je bank, niet een link of nummer uit het bericht.",
    "pl": "Zanim cokolwiek zrobisz, sprawdź przez oficjalny numer na karcie lub oficjalną stronę banku, a nie przez link lub numer z wiadomości.",
    "pt": "Antes de fazer qualquer coisa, confira pelo número oficial do seu cartão ou pelo site oficial do banco, e não por um link ou número da mensagem.",
    "ta": "எதையும் செய்வதற்கு முன், உங்கள் அட்டையில் உள்ள அதிகாரப்பூர்வ எண் அல்லது வங்கியின் அதிகாரப்பூர்வ இணையதளம் மூலம் சரிபார்க்கவும். செய்தியில் உள்ள இணைப்பு அல்லது எண்ணைப் பயன்படுத்த வேண்டாம்.",
    "ja": "何かをする前に、カードに記載の公式の番号か銀行の公式サイトで確認してください。メッセージ内のリンクや番号は使わないでください。",
    "ko": "무엇을 하기 전에, 카드에 적힌 공식 번호나 은행 공식 홈페이지로 확인하세요. 메시지에 있는 링크나 번호는 사용하지 마세요.",
    "id": "Sebelum melakukan apa pun, periksa menggunakan nomor resmi di kartu Anda atau situs resmi bank, bukan tautan atau nomor di dalam pesan.",
    "vi": "Trước khi làm bất cứ điều gì, hãy kiểm tra qua số chính thức trên thẻ hoặc trang web chính thức của ngân hàng, không dùng liên kết hay số trong tin nhắn.",
    "bn": "কোনো কিছু করার আগে, আপনার কার্ডে দেওয়া অফিসিয়াল নম্বরে বা ব্যাংকের অফিসিয়াল ওয়েবসাইটে যাচাই করুন, বার্তার কোনো লিংক বা নম্বরে নয়।",
    "zh": "在采取任何行动之前，请使用银行卡上的官方号码或银行官方网站进行核实，不要使用信息中的链接或号码。",
    "en": (
        "Before you do anything, check using the official number on your card "
        "or the bank's official website, not a link or number in the message."
    ),
    "fr": (
        "Avant d'agir, vérifiez avec le numéro officiel figurant sur votre carte "
        "ou sur le site officiel de votre banque, et non avec un lien ou un numéro du message."
    ),
    "de": (
        "Prüfen Sie zuerst über die offizielle Nummer auf Ihrer Karte oder über die offizielle Website "
        "Ihrer Bank, nicht über einen Link oder eine Nummer in der Nachricht."
    ),
    "es": (
        "Antes de hacer nada, compruébelo con el número oficial de su tarjeta o en la web oficial de su banco, "
        "no con un enlace o un número del mensaje."
    ),
    "hi": (
        "कुछ भी करने से पहले, अपने कार्ड पर दिए आधिकारिक नंबर या बैंक की आधिकारिक वेबसाइट से जाँच करें, "
        "संदेश में दिए किसी लिंक या नंबर से नहीं।"
    ),
}

VERDICTS = ("SCAM", "SUSPICIOUS", "LOOKS OK")

RESCUE_NOTE = ("Reply now, briefly: under 150 words plus any table, in the reply language. Put only the reply inside "
               "<answer></answer>. Do not describe yourself.")
LENGTH_RETRY = ("Your last reply was too long. Reply again with only the answer, "
                "in under 150 words plus any table.")

SCAM_FALLBACK = (
    "I could not check this message fully, so please treat it as suspicious. "
    "Do not click any link, reply to the message, or pay anything it asks for."
)

SCAM_QUERY = CFG.get("search", {}).get(
    "scam_query", "official guidance on recognising scam messages from banks and government"
)


def lang_prefix(code):
    return (code or DEFAULT_LANGUAGE).split("-")[0].lower()


def pick(table, code):
    return table.get(lang_prefix(code), table["en"])


# Questions that ask for the best way, a comparison, or options: research first.
RESEARCH_RE = re.compile(
    r"\b(best (way|method|technique|option|app|tool|approach|practice)s?|which (one |is |option |method )?(is )?(better|best)"
    r"|better (way|option|method)|options? for|compare|comparison|recommend\w*|technique|how should i)\b",
    re.IGNORECASE,
)


# The person wants everything Auriv saved about them deleted. The page shows a confirmation card.
DELETE_DATA_RE = re.compile(
    r"\b(clear|delete|erase|remove|wipe|reset)\b[^.?!]{0,30}\b(all )?(my|of my|mine)\b[^.?!]{0,20}\b(data|information|info|history|everything|goals|details)\b"
    r"|\b(clear|delete|erase|wipe) (all )?(my )?data\b|\bforget (me|everything about me)\b|\bdata of mine\b"
    r"|(मेरा|मेरी|मेरे).{0,20}(डेटा|डाटा|जानकारी).{0,20}(हटा|मिटा|डिलीट)|(डेटा|डाटा).{0,10}(हटा|मिटा|डिलीट)"
    r"|supprimer (toutes )?mes données|meine daten löschen|borrar (todos )?mis datos|cancella (tutti )?i miei dati"
    r"|apagar (todos )?(os )?meus dados|verwijder mijn gegevens|usuń moje dane|hapus (semua )?data saya|xóa (tất cả )?dữ liệu của tôi"
    r"|verilerimi sil|futa data yangu|আমার ডেটা মুছে|என் தரவை நீக்கு|データを(全部)?消して|删除我的(所有)?数据|내 데이터(를)? 삭제",
    re.IGNORECASE)


# ---------- Routing ----------

def route(message, mode="normal"):
    """Return the name of the skill that should handle this message."""
    if mode == "rephrase":
        return "rephrase"
    if EMERGENCY_RE.search(message) or EMERGENCY_NATIVE_RE.search(message):
        return "emergency"
    if DELETE_DATA_RE.search(message):
        return "delete_data"

    signals = len(SCAM_SIGNAL_RE.findall(message))
    if signals >= 2 or (signals >= 1 and RECEIVED_RE.search(message)) or SCAM_INTENT_RE.search(message):
        return "scam"

    dated = len(DATE_WORD_RE.findall(message)) >= 3 and not PROFESSIONAL_RE.search(message)
    if (SCHEDULE_RE.search(message) or dated) and not RESEARCH_RE.search(message):
        return "schedule"
    if TEACH_RE.search(message):
        return "learning_coach"
    if OVERWHELM_RE.search(message):
        return "overwhelm"
    if GOAL_INTENT_RE.search(message) and TIMEFRAME_RE.search(message) and not PROFESSIONAL_RE.search(message):
        return "goal_planner"
    # The person talks about a goal in their own words ("my goal is...", "I have to work on a goal", "लक्ष्य").
    if GOAL_WORD_RE.search(message) and not QUESTION_START_RE.match(message) and not PROFESSIONAL_RE.search(message):
        return "goal_planner"
    if WANT_LEARN_RE.search(message) and not PROFESSIONAL_RE.search(message):
        return "learning_coach"
    if ACTION_RE.search(message):
        return "action"
    if WRITE_RE.search(message):
        return "task_helper"
    if VAGUE_RE.search(message):
        return "clarify"
    if STUCK_RE.search(message):
        return "guide_step"
    if CURRENT_RE.search(message):
        return "explain"  # gather_sources still searches, because needs_search sees "latest"
    if PROFESSIONAL_RE.search(message):
        return "professional"
    if RESEARCH_RE.search(message):
        return "research"
    if PLANNING_RE.search(message):
        return "goal_planner"
    return "explain"


# ---------- Model and search ----------

def skill_prompt(skill):
    if skill in ("explain", "rephrase", "emergency"):
        return ""
    return core.load_prompt(f"skills/{skill}")


# ---------- Which model answers ----------
# Main model (Nemotron-3.5-Lightning) for everyday replies; Ultra for careful reasoning; Nano for quick background jobs.
DEEP_SKILLS = {"research"}


INTENT_LABELS = ["goal_planner", "schedule", "learning_coach", "scam", "overwhelm", "professional", "research", "action", "explain"]
INTENT_PROMPT = """Classify the person's message (it can be in any language) with exactly one label:
goal_planner: a goal or target to work towards, often with a time frame (prepare, practise, learn, finish or achieve something by a date)
schedule: several meetings, classes, appointments or deadlines to organise into a plan
learning_coach: wants to be taught or to learn or practise a skill, language or subject, with no deadline
scam: asks whether a message, call, email or link they received is real, safe or a scam
overwhelm: too much to do and does not know where to start
professional: a health, legal, money, housing or pet problem that needs a professional
research: wants options compared, or the best way or best choice
action: asks you to do something for them (pay, send, book, buy, log in)
explain: anything else (a question, a how-to, a fact, a chat)
Reply with only the label."""


def classify_intent(message):
    """One short call to the fast model. Returns a label, or None if it fails (the normal route is kept)."""
    model = (CFG.get("models") or {}).get("fast") or CFG["model"]
    try:
        response = _create(model, dict(messages=[{"role": "system", "content": INTENT_PROMPT},
                                                 {"role": "user", "content": message[:600]}],
                                       max_tokens=12, temperature=0), timeout=8)
        text = (response.choices[0].message.content or "").strip().lower()
    except Exception as error:
        core.log_call({"intent_model_error": type(error).__name__})
        return None
    label = re.sub(r"[^a-z_]", "", text.split()[0]) if text else ""
    return label if label in INTENT_LABELS else None


def model_for(skill, message="", language_code=None):
    models = CFG.get("models", {}) or {}
    non_english = lang_prefix(language_code or "en") != "en" or re.search(r"[^\x00-\u024F\s]", message or "")
    if non_english and (skill == "learning_coach" or (lang_prefix(language_code or "en") == "hi" and skill in ("schedule", "goal_planner"))):
        return models.get("deep") or CFG["model"]
    if skill == "goal_draft":
        return models.get("fast") or CFG["model"]
    # "Teach me" alone is a lesson (fast model); Ultra is for real concept questions such as helicity or MHD.
    concept_text = re.sub(r"\bteach me\b", "", message or "", flags=re.IGNORECASE)
    if skill in DEEP_SKILLS or (skill in ("explain", "professional", "learning_coach") and CONCEPT_RE.search(concept_text)):
        return models.get("deep") or CFG["model"]
    return CFG["model"]


def thinking_for(model):
    """Thinking on or off for this model (config "thinking"); the old single "enable_thinking" setting still works."""
    models = CFG.get("models", {}) or {}
    role = "deep" if model == models.get("deep") else "fast" if model == models.get("fast") else "main"
    settings = CFG.get("thinking") or {}
    if role in settings:
        return bool(settings[role])
    return bool(CFG.get("enable_thinking", False))


def _create(model, kwargs, timeout=None):
    """One request. Nemotron 3 reads thinking from chat_template_kwargs (NVIDIA's documented field).
    If the server rejects that field, the same request is sent once without it."""
    extra = {"timeout": timeout} if timeout else {}
    body = {"chat_template_kwargs": {"enable_thinking": thinking_for(model)}}
    try:
        return core.ai.chat.completions.create(model=model, extra_body=body, **kwargs, **extra)
    except Exception as error:
        if "400" in str(error) or "BadRequest" in type(error).__name__:
            core.log_call({"model": model, "note": "thinking setting rejected, retried without it"})
            return core.ai.chat.completions.create(model=model, **kwargs, **extra)
        raise


def create_completion(model, **kwargs):
    """Call one model. If a non-main model fails (unknown ID, outage, too slow), fall back to the main model."""
    try:
        timeout = None if model == CFG["model"] else 25   # a slow extra model must not keep the person waiting
        return _create(model, kwargs, timeout), model
    except Exception as error:
        if model == CFG["model"]:
            raise
        core.log_call({"model_fallback": model, "error": type(error).__name__})
        return _create(CFG["model"], kwargs), CFG["model"]


# Phone numbers must come from the search results or the verified list, never from the model's memory.
PHONE_RE = re.compile(r"(?<![\w.+/-])(\+?\d[\d \-]{5,}\d)(?!\w|\.\d)")


def invented_numbers(answer, evidence):
    seen = re.sub(r"\D", "", evidence)
    out = []
    for m in PHONE_RE.finditer(answer):
        raw = m.group(1).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 7 or re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) or re.fullmatch(r"(19|20)\d{2}\s*-\s*(19|20)?\d{2}", raw):
            continue
        if digits not in seen:
            out.append(raw)
    return out


def remove_numbers(answer, numbers):
    for n in numbers:
        answer = answer.replace("(" + n + ")", "(number on their official website)")
        answer = answer.replace(n, "(number on their official website)")
    return answer


# Languages with their own script: a reply written mostly in English letters is in the wrong language.
SCRIPT_RANGES = {"hi": "\u0900-\u097F", "bn": "\u0980-\u09FF", "ta": "\u0B80-\u0BFF", "ja": "\u3040-\u30FF\u4E00-\u9FFF",
                 "zh": "\u4E00-\u9FFF", "ko": "\uAC00-\uD7AF"}


def wrong_script(answer, language_code):
    rng = SCRIPT_RANGES.get(lang_prefix(language_code or "en"))
    if not rng:
        return False
    text = re.sub(r"\{\{[a-z]{2}\|[^}]*\}\}|\([^)]*\)|https?://\S+|\\\(.*?\\\)|\\\[.*?\\\]", " ", answer, flags=re.S)
    native = len(re.findall("[" + rng + "]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return native + latin > 40 and native < 0.35 * (native + latin)


def call_model(system_text, user_text, skill, history=None, model=None, user_message="", language_code=None):
    model = model or CFG["model"]
    messages = [{"role": "system", "content": system_text}]
    messages += list(history or [])
    messages.append({"role": "user", "content": user_text})
    last_clean = None
    for attempt in range(CFG["max_attempts"]):
        response, model = create_completion(
            model, messages=messages, max_tokens=CFG["max_tokens"], temperature=CFG["temperature"])
        choice = response.choices[0]
        text = choice.message.content or ""
        answer = core.extract_answer(text)

        core.log_call({
            "skill": skill,
            "model": model,
            "attempt": attempt,
            "finish_reason": choice.finish_reason,
            "completion_tokens": response.usage.completion_tokens,
            "clean": answer is not None,
        })

        correction = None
        if answer and choice.finish_reason == "stop":
            strict, correction = quality_problem(answer, skill, user_message)
            if (not correction and skill == "learning_coach" and "{{" in answer
                    and wants_place_lesson(user_message + " " + " ".join(h["content"] for h in (history or [])[-4:] if h["role"] == "user"))):
                strict, correction = False, ("The person wants to learn about the place and its culture, not its language. "
                                             "Write the lesson again without any language phrases, {{..}} markers or word-by-word lines, "
                                             "and make Practice and Next about the place itself.")
            if not correction and wrong_script(answer, language_code):
                strict, correction = False, ("Write the whole reply again in " + LANGUAGE_NAMES.get(language_code, "the person's language")
                                             + ", in its own script. Keep only names and a few key terms in English, in brackets.")
            invented = invented_numbers(answer, system_text + " " + user_text)
            if invented:
                core.log_call({"skill": skill, "numbers_removed": len(invented)})
                answer = remove_numbers(answer, invented)
            if not correction:
                return answer, False
            core.log_call({"skill": skill, "attempt": attempt, "quality": correction[:60], "strict": strict})
            if not strict and last_clean is None:
                last_clean = answer  # usable but imperfect; shown only if no better reply comes
            deep = (CFG.get("models") or {}).get("deep")
            if strict and deep and model != deep and correction.startswith(("You are Auriv", "You can teach")):
                core.log_call({"skill": skill, "switch_model": "deep"})
                model = deep  # this model keeps describing itself: try the other one
        elif answer and "</answer>" in text.lower() and not quality_problem(answer, skill, user_message)[0]:
            last_clean = answer  # only a complete, closed answer is kept
        if not answer:
            core.log_call({"skill": skill, "attempt": attempt, "rejected": "empty_or_leak", "chars": len(text)})

        messages.append({"role": "assistant", "content": text})
        if correction:
            messages.append({"role": "user", "content": correction})
        elif choice.finish_reason == "length":
            messages.append({"role": "user", "content": LENGTH_RETRY})
        else:
            messages.append({"role": "user", "content": core.load_prompt("format_retry")})

    if last_clean:
        core.log_call({"skill": skill, "used_last_clean": True})
        return last_clean, False
    try:
        rescue_msgs = [{"role": "system", "content": system_text},
                       {"role": "user", "content": user_text + "\n\n" + RESCUE_NOTE}]
        rescue_model = (CFG.get("models") or {}).get("deep") or CFG["model"]
        response, _ = create_completion(rescue_model, messages=rescue_msgs, max_tokens=1500, temperature=0.3)
        choice = response.choices[0]
        answer = core.extract_answer(choice.message.content or "")
        if answer and choice.finish_reason in ("stop", "length") and not quality_problem(answer, skill, user_message)[0]:
            core.log_call({"skill": skill, "rescued": True})
            return answer, False
        core.log_call({"skill": skill, "rescue_failed": choice.finish_reason, "clean": answer is not None})
    except Exception as error:
        core.log_call({"skill": skill, "rescue_error": type(error).__name__})
    core.log_call({"skill": skill, "fallback": True})
    return core.load_prompt("fallback"), True


# Home safety tasks: always ground the reply in official guidance, never the model's memory alone.
# Each pattern maps to a fixed English search query, so messages in any language get good sources.
HOME_SAFETY_TOPICS = [
    (re.compile(r"\b(smell (of )?gas|gas smell|smells? like gas)\b|गैस की (बदबू|गंध)", re.IGNORECASE),
     "smell gas at home what to do gas leak emergency official guidance"),
    (re.compile(r"\b(lpg|gas (cylinder|bottle|leak|stove|hob|regulator)|cylinder|regulator)\b"
                r"|गैस|सिलेंडर|सिलिंडर|रेगुलेटर|গ্যাস|সিলিন্ডার|எரிவாயு|சிலிண்டர்|bombona|bouteille de gaz|gasflasche|botijão",
                re.IGNORECASE),
     "how to safely connect an LPG gas cylinder regulator and check for leaks official safety guidance"),
    (re.compile(r"\b(fuse|wiring|socket|plug (sparks|burning)|circuit breaker|electric shock|electrical)\b"
                r"|बिजली का (तार|झटका)|शॉर्ट सर्किट|ফিউজ|மின்சார",
                re.IGNORECASE),
     "home electrical safety what to do official guidance"),
    (re.compile(r"\b(geyser|boiler|water heater|carbon monoxide)\b|गीजर|गीज़र", re.IGNORECASE),
     "water heater geyser boiler and carbon monoxide safety official guidance"),
]


def home_safety_query(message):
    for pattern, query in HOME_SAFETY_TOPICS:
        if pattern.search(message):
            return query
    return None


# How-to and task questions get one search, so the person has a link to check for themselves.
TASK_RE = re.compile(
    r"\b(how (do|can|should|would) (i|we)|how to|steps? (to|for)|set ?up|install|reset|fix|repair|apply for"
    r"|register|renew|connect|replace|cancel|update|download|unblock|recover|link my|change my)\b"
    r"|कैसे|কীভাবে|எப்படி|cómo|comment (faire|puis)|wie (kann|mache)|come (posso|faccio|si)|hoe (kan|moet)"
    r"|jak (mogę|zrobić)|como (faço|posso)|どうやって|方法|如何|怎么|어떻게|bagaimana|làm sao|làm thế nào|nasıl|jinsi ya",
    re.IGNORECASE,
)
# Personal planning messages (schedules, goals) are not sent to search: they can contain private details.
TASK_SEARCH_SKILLS = {"explain", "task_helper", "guide_step", "professional", "learning_coach", "action"}

OFFICIAL_RE = re.compile(
    r"(\.gov(\.[a-z]{2})?|\.gouv\.fr|\.gob\.es|\.go\.(jp|id|kr|ke)|\.gc\.ca|\.nic\.in|\.nhs\.uk|\.police\.uk|\.europa\.eu"
    r"|\.edu|\.ac\.[a-z]{2}|\.who\.int|\.un\.org|service-public\.fr|bund\.de|citizensadvice\.org\.uk|india\.gov\.in)(/|$)",
    re.IGNORECASE)


# Country for each language, used to prefer local official sources (rules differ between countries).
COUNTRY_FOR_LANGUAGE = {
    "en-GB": ("United Kingdom", r"\.(gov|nhs|org|co)\.uk$|\.uk$"),
    "en-US": ("United States", r"\.gov$|\.us$"),
    "en-IN": ("India", r"\.(gov|nic|org|co)\.in$|\.in$"),
    "hi-IN": ("India", r"\.(gov|nic|org|co)\.in$|\.in$"),
    "bn-IN": ("India", r"\.(gov|nic|org|co)\.in$|\.in$"),
    "ta-IN": ("India", r"\.(gov|nic|org|co)\.in$|\.in$"),
    "fr-FR": ("France", r"\.gouv\.fr$|\.fr$"),
    "de-DE": ("Germany", r"\.de$"),
    "es-ES": ("Spain", r"\.gob\.es$|\.es$"),
    "it-IT": ("Italy", r"\.gov\.it$|\.it$"),
    "nl-NL": ("Netherlands", r"\.nl$"),
    "pl-PL": ("Poland", r"\.gov\.pl$|\.pl$"),
    "pt-BR": ("Brazil", r"\.gov\.br$|\.br$"),
    "ja-JP": ("Japan", r"\.go\.jp$|\.jp$"),
    "zh-CN": ("China", r"\.gov\.cn$|\.cn$"),
    "ko-KR": ("South Korea", r"\.go\.kr$|\.kr$"),
    "id-ID": ("Indonesia", r"\.go\.id$|\.id$"),
    "vi-VN": ("Vietnam", r"\.gov\.vn$|\.vn$"),
    "tr-TR": ("Turkey", r"\.gov\.tr$|\.tr$"),
    "sw-KE": ("Kenya", r"\.go\.ke$|\.ke$"),
}


# Countries offered on the first screen (codes match helplines.yaml).
COUNTRY_INFO = {
    "GB": ("United Kingdom", r"\.(gov|nhs|org|co|police)\.uk$|\.uk$"),
    "US": ("United States", r"\.gov$|\.us$"),
    "IN": ("India", r"\.(gov|nic|org|co)\.in$|\.in$"),
    "FR": ("France", r"\.gouv\.fr$|\.fr$"),
    "DE": ("Germany", r"\.de$"),
    "ES": ("Spain", r"\.gob\.es$|\.es$"),
    "IT": ("Italy", r"\.gov\.it$|\.it$"),
    "BR": ("Brazil", r"\.gov\.br$|\.br$"),
    "JP": ("Japan", r"\.go\.jp$|\.jp$"),
    "ID": ("Indonesia", r"\.go\.id$|\.id$"),
}


def country_info(country, language_code):
    """The person's chosen country wins; otherwise guess from the language."""
    return COUNTRY_INFO.get(country) or COUNTRY_FOR_LANGUAGE.get(language_code) or (None, None)


SCAM_REPORT_LEAD = {"en": "Report it:", "hi": "शिकायत करें:", "es": "Denúncialo:", "fr": "Signalez-le :"}


def scam_report_line(country, language_code):
    """Verified reporting route for scams (helplines.yaml, scam_report), shown under every message check."""
    import yaml
    from pathlib import Path
    try:
        data = yaml.safe_load((Path(__file__).parent / "helplines.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    entry = (data.get("countries") or {}).get(country) or {}
    route = entry.get("scam_report")
    if not route or entry.get("status") != "verified":
        return ""
    return "📣 " + pick(SCAM_REPORT_LEAD, language_code) + " " + route


def emergency_numbers(country):
    """Verified numbers for the emergency reply, read from helplines.yaml."""
    import yaml
    from pathlib import Path
    try:
        data = yaml.safe_load((Path(__file__).parent / "helplines.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    entry = (data.get("countries") or {}).get(country) or {}
    if entry.get("status") != "verified":
        return []
    order = ["emergency", "fire_ambulance", "ambulance", "police"]
    nums = sorted((n for n in entry.get("numbers", []) if n.get("kind") in order), key=lambda n: order.index(n["kind"]))
    seen = []
    for n in nums:
        if n["number"] not in seen:
            seen.append(n["number"])
    return seen[:3]


def _host(url):
    return re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()


def rank_sources(sources, language_code=None, country=None):
    """Local official sites first, then other official sites, then local sites; otherwise keep search order."""
    local = country_info(country, language_code)[1]

    def score(src):
        host = _host(src[1])
        official = bool(OFFICIAL_RE.search(host + "/"))
        is_local = bool(local and re.search(local, host))
        return 0 if official and is_local else 1 if official else 2 if is_local else 3
    return sorted(sources, key=score)


# Word lists below cover all 20 app languages. Latin-script words use \b; other scripts match directly.

# The person asks for a link or source: search, using the earlier topic if this message has none.
LINK_RE = re.compile(
    r"\b(links?|sources?|websites?|urls?|where (can|do) i (read|find|see)|enlace|enlaces|fuente|lien|liens|source|quelle|quellen"
    r"|fonte|fonti|bron|bronnen|źródło|link do|tautan|sumber|liên kết|nguồn|bağlantı|kaynak|kiungo|chanzo)\b"
    r"|लिंक|स्रोत|वेबसाइट|লিংক|উৎস|ওয়েবসাইট|இணைப்பு|மூலம்|இணையதளம்|リンク|出典|链接|来源|网站|링크|출처|웹사이트",
    re.IGNORECASE)

# Concept and learning questions: ground the explanation in sources, not memory alone.
CONCEPT_RE = re.compile(
    r"\b(understand|concept|theory|explain|definition|teach me|what does .{1,40} mean"
    r"|comprendre|expliquer|concept|théorie|concepto|teoría|explicar|entender|konzept|theorie|erklären|verstehen"
    r"|concetto|teoria|spiegare|capire|begrip|theorie|uitleggen|begrijpen|pojęcie|teoria|wyjaśnij|zrozumieć"
    r"|conceito|explicar|entender|konsep|teori|jelaskan|memahami|khái niệm|lý thuyết|giải thích|hiểu"
    r"|kavram|teori|açıkla|anlamak|dhana|nadharia|eleza|kuelewa)\b"
    r"|समझ|अवधारणा|सिद्धांत|परिभाषा|ধারণা|তত্ত্ব|বুঝতে|ব্যাখ্যা|கருத்து|கோட்பாடு|புரிந்து|விளக்க"
    r"|概念|理論|説明|理解|理论|解释|개념|이론|설명|이해",
    re.IGNORECASE)

# Factual look-ups about people, works, places or lists.
LOOKUP_RE = re.compile(
    r"\b(who (is|was|wrote)|which (books|poems|songs|works)|list of|written by|poems? (of|by)|books? (of|by)"
    r"|qui (est|était|a écrit)|poèmes|quién (es|fue|escribió)|poemas|wer (ist|war|schrieb)|gedichte"
    r"|chi (è|era|ha scritto)|poesie|wie (is|was|schreef)|gedichten|kto (to|jest|był|napisał)|wiersze"
    r"|quem (é|foi|escreveu)|siapa|puisi|karya|ai là|bài thơ|tác phẩm|kimdir|kim yazdı|şiirleri|eserleri"
    r"|ni nani|mashairi|vitabu vya)\b"
    r"|कौन|कविताएँ|कविताएं|कविता|किताबें|रचनाएँ|रचनाएं|कहानियों|कहानियाँ|कहानियां|लेखक"
    r"|কে ছিলেন|কে লিখেছেন|কবিতা|বই|যার লেখা|யார்|கவிதை|நூல்கள்|誰|作品|詩|谁|作者|诗|누구|작품|시집",
    re.IGNORECASE)

# The model says it does not know: search and answer again.
UNSURE_RE = re.compile(
    r"i don'?t have (information|details|data|any information)|i do not have (information|details)"
    r"|not (aware|familiar) with|no (reliable )?information|i'?m not sure"
    r"|je ne (sais|dispose)|je n'ai pas d'information|no tengo informaci|no lo sé|keine informationen|weiß ich nicht"
    r"|non ho informazioni|non lo so|geen informatie|weet ik niet|nie mam informacji|nie wiem"
    r"|não tenho informaç|não sei|tidak memiliki informasi|tidak tahu|không có thông tin|tôi không biết"
    r"|bilgim yok|bilgiye sahip değilim|bilmiyorum|sina taarifa|sijui"
    r"|जानकारी नहीं|पता नहीं|তথ্য নেই|জানা নেই|தகவல் இல்லை|தெரியவில்லை|情報がありません|わかりません"
    r"|没有.{0,6}信息|不清楚|不知道|정보가 없|모르겠",
    re.IGNORECASE)

# A fresh question, not a follow-up to the task in progress.
NEW_QUESTION_RE = re.compile(
    r"^\s*[¿¡]?\s*(what (is|are|was|does)|who|why|tell me about|qu'est-ce que|qui|pourquoi|parle-moi de"
    r"|qué es|quién|por qué|háblame de|was ist|wer|warum|erzähl mir von|cos'è|che cos'è|chi|perché|parlami di"
    r"|wat is|wie|waarom|vertel me over|co to jest|kto|dlaczego|opowiedz mi o|o que é|quem|por que|me fale sobre"
    r"|apa itu|siapa|mengapa|ceritakan|tại sao|kể cho tôi)\b"
    r"|बताइए|बताओ|बताएं|क्या है|কী\s|কেন|বলুন|என்ன|ஏன்|சொல்லுங்கள்|とは|教えて|是什么|为什么|告诉我|무엇|왜|알려 주"
    r"|là gì|nedir|neden|anlat|ni nini|kwa nini|nieleze",
    re.IGNORECASE)
# Language lessons: the model teaches these itself, so no search (and no delay) is needed.
LANGUAGE_SUBJECT_RE = re.compile(
    r"\b(english|hindi|bengali|bangla|tamil|telugu|marathi|urdu|punjabi|gujarati|french|german|spanish|italian|portuguese"
    r"|dutch|polish|turkish|japanese|chinese|mandarin|korean|vietnamese|indonesian|swahili|arabic|russian|language)\b"
    r"|अंग्रेज़ी|अंग्रेजी|इंग्लिश|हिंदी|हिन्दी|बांग्ला|तमिल|भाषा|inglés|ingles|anglais|englisch|inglese|inglês|bahasa inggris|英語|英语|영어",
    re.IGNORECASE)

# "Learn about France / its culture / भारत के बारे में": a lesson about the place, not its language.
ABOUT_PLACE_RE = re.compile(
    r"\b(about|on)\s+(the\s+)?[A-Z][a-z]+|\b(culture|history|geography|festivals?|traditions?|people|cuisine|food) of\b|\band its (culture|history|people|food)\b"
    r"|के बारे में|की संस्कृति|का इतिहास|sur la|über|sobre", re.UNICODE)
ASKS_FOR_LANGUAGE_RE = re.compile(
    r"\b(french|hindi|english|spanish|german|italian|japanese|chinese|mandarin|korean|portuguese|arabic|russian|bengali|tamil|language|speak|say|words?|phrases?|pronounce)\b"
    r"|भाषा|बोलना|बोलने|फ्रेंच|अंग्रेज़ी|अंग्रेजी|हिंदी", re.IGNORECASE)


def wants_place_lesson(message):
    return bool(ABOUT_PLACE_RE.search(message or "")) and not ASKS_FOR_LANGUAGE_RE.search(message or "")


PERSONAL_SKILLS_NO_SEARCH = {"schedule", "goal_planner", "overwhelm", "clarify", "rephrase", "scam", "emergency"}


# Short follow-ups ("what about for two people?", "and in French?") need the earlier question to make a useful search.
FOLLOW_UP_RE = re.compile(r"^\s*(and|also|what about|how about|but|ok|okay|then|aur|और|फिर|et|y|und|e)\b|^\W*(\w+\W*){1,4}$", re.IGNORECASE)


def search_topic(message, history):
    """A link request often has no topic ("give me a link"): add the person's previous message."""
    if (LINK_RE.search(message) or FOLLOW_UP_RE.search(message)) and history:
        earlier = [h["content"] for h in history if h["role"] == "user"]
        if earlier:
            return (earlier[-1] + " " + message)[:300]
    return message[:300]


def hands_on_search(message, history, language_code=None, country=None):
    """Learning a physical skill: search for beginner technique guides and videos (video sites allowed here only)."""
    topic = search_topic(message, history)
    try:
        context, sources = core.search_web(topic + " beginner lessons basic technique video", allow_video=True)
        return context, rank_sources(sources, language_code, country), bool(context)
    except Exception:
        return "", [], False


def search_now(query, language_code=None, country=None):
    try:
        context, sources = core.search_web(query)
        return context, rank_sources(sources, language_code, country), bool(context)
    except Exception:
        return "", [], False


# Official matters: documents, law, tax, land, benefits, health and safety. These must rest on official sources.
OFFICIAL_Q_RE = re.compile(
    r"\b(apply|application|passport|visa|licen[cs]e|permit|tax|benefits?|pension|register|registration|land|property|deed"
    r"|certificate|documents?|paperwork|id card|court|law|legal|rights|government|official|council|tenancy|eviction"
    r"|insurance|vaccin\w*|medicine|scheme|subsidy|loan|bank account|aadhaar|pan card|ration card)\b"
    r"|पासपोर्ट|वीज़ा|वीजा|टैक्स|कर विभाग|जमीन|ज़मीन|भूमि|कागजात|काग़ज़ात|दस्तावेज़|दस्तावेज|प्रमाणपत्र|सरकारी|पंजीकरण|रजिस्ट्री"
    r"|लाइसेंस|पेंशन|कानून|सरकारी योजना|सब्सिडी|आधार|राशन कार्ड|बीमा|ऋण|লাইসেন্স|জমি|নথি|সরকারি|நிலம்|ஆவணங்கள்|அரசு"
    r"|impôt|démarche|titre de séjour|steuer|antrag|behörde|impuesto|trámite|tasse|documenti|imposto|documentos"
    r"|書類|税金|申請|文件|税|申请|서류|세금|신청|pajak|dokumen|izin|thuế|giấy tờ|vergi|belge|kodi|hati",
    re.IGNORECASE)

# Official and public-service sites to search when the first results have none (by country).
OFFICIAL_DOMAINS = {
    "GB": ["gov.uk", "nhs.uk", "citizensadvice.org.uk", "police.uk", "hmrc.gov.uk"],
    "US": ["usa.gov", "irs.gov", "ssa.gov", "uscis.gov", "consumer.ftc.gov", "cdc.gov", "medicare.gov"],
    "IN": ["india.gov.in", "gov.in", "nic.in", "uidai.gov.in", "rbi.org.in", "incometax.gov.in"],
    "FR": ["service-public.fr", "gouv.fr", "ameli.fr", "impots.gouv.fr"],
    "DE": ["bund.de", "bundesregierung.de", "verbraucherzentrale.de", "bundesgesundheitsministerium.de"],
    "ES": ["administracion.gob.es", "gob.es", "agenciatributaria.es", "seg-social.es"],
    "IT": ["gov.it", "governo.it", "inps.it", "agenziaentrate.gov.it", "salute.gov.it"],
    "BR": ["gov.br"],
    "JP": ["go.jp", "e-gov.go.jp", "japan.travel"],
    "ID": ["go.id", "indonesia.go.id", "kemkes.go.id"],
}
LANGUAGE_COUNTRY = {"en-GB": "GB", "en-US": "US", "en-IN": "IN", "hi-IN": "IN", "bn-IN": "IN", "ta-IN": "IN",
                    "fr-FR": "FR", "de-DE": "DE", "es-ES": "ES", "it-IT": "IT", "pt-BR": "BR", "ja-JP": "JP", "id-ID": "ID"}


def is_official_question(message, skill):
    return skill == "professional" or bool(OFFICIAL_Q_RE.search(message)) or bool(home_safety_query(message))


def gather_sources(message, skill, language_code=None, history=None, country=None):
    context, sources, used = _gather_sources(message, skill, language_code, history or [], country)
    sources = rank_sources(sources, language_code, country)
    # Official matter, but no official site found: search official sites only, and put them first.
    # Never for scam checks (the pasted message must not be searched) or personal plans.
    if (used and skill not in PERSONAL_SKILLS_NO_SEARCH and is_official_question(message, skill) and not PET_RE.search(message)
            and not any(OFFICIAL_RE.search(_host(u) + "/") for _, u in sources)):
        domains = OFFICIAL_DOMAINS.get(country) or OFFICIAL_DOMAINS.get(LANGUAGE_COUNTRY.get(language_code, ""), [])
        if domains:
            try:
                topic = search_topic(message, list(history or []))
                ctx2, src2 = core.search_web(topic, include_domains=domains)
                ctx2, src2 = relevant_blocks(ctx2, src2, topic)
            except Exception:
                ctx2, src2 = "", []
            if ctx2:
                core.log_call({"skill": skill, "official_search": True, "results": len(src2)})
                sources = src2 + [s for s in sources if s not in src2]
                context = ctx2 + "\n\n" + context
    if used and PET_RE.search(message) and PET_DOMAINS.get(country) and not any(
            any(d in _host(u) for d in PET_DOMAINS[country]) for _, u in sources):
        try:
            ctx3, src3 = core.search_web(search_topic(message, list(history or [])), include_domains=PET_DOMAINS[country])
            ctx3, src3 = relevant_blocks(ctx3, src3, message)
        except Exception:
            ctx3, src3 = "", []
        if ctx3:
            sources = src3 + [s for s in sources if s not in src3]
            context = ctx3 + "\n\n" + context
    return context, sources, used


PET_DOMAINS = {
    "GB": ["pdsa.org.uk", "rspca.org.uk", "bluecross.org.uk", "battersea.org.uk"],
    "US": ["aspca.org", "avma.org"],
}


# Rules differ by country, so these searches name the person's country (a UK passport question must not get US pages).
COUNTRY_SEARCH_SKILLS = {"explain", "task_helper", "guide_step", "professional", "action", "scam"}
PET_RE = re.compile(r"\b(vet|pet|dog|puppy|cat|kitten|rabbit|bird|hamster|parrot|cow|goat)s?\b|कुत्ता|कुत्ते|बिल्ली|पालतू|पशु", re.IGNORECASE)
STOP_WORDS = set(("what when where which with from that this have your their there about would could should into does please help need want "
                  "the and for are can how you my me our its isn not but all any get got was has had who why way use one out new now").split())


def relevant_blocks(context, sources, query):
    """Keep only official results whose title shares a word with the question (gov-only searches can return unrelated pages)."""
    words = {w for w in re.findall(r"\w{3,}", query.lower()) if w not in STOP_WORDS}
    if not words:
        return context, sources
    keep = [(t, u) for t, u in sources if words & set(re.findall(r"\w{3,}", (t + " " + u).lower()))]
    blocks = [b for b in context.split("\n\nTitle: ") if any(u in b for _, u in keep)]
    text = "\n\nTitle: ".join(blocks)
    if text and not text.startswith("Title: "):
        text = "Title: " + text
    return text, keep


def _gather_sources(message, skill, language_code=None, history=(), country=None):
    safety_query = home_safety_query(message)
    place = country_info(country, language_code)[0]
    place_name = place
    if safety_query and place:
        safety_query += " " + place
    if skill == "task_helper" and WRITE_RE.search(message):
        return "", [], False  # a draft to copy needs no search, and the person's details stay private
    if skill == "scam":
        query = SCAM_QUERY  # the pasted message is never sent to search
    elif skill == "research":
        query = message  # the topic is searched; scam checks still never send the pasted message
    elif safety_query:
        query = safety_query
    elif skill in TASK_SEARCH_SKILLS and TASK_RE.search(message):
        query = message
    elif skill == "learning_coach":
        if LANGUAGE_SUBJECT_RE.search(message) or not (TEACH_RE.search(message) or WANT_LEARN_RE.search(message)):
            return "", [], False  # language lessons and lesson follow-ups come from the model, with no search delay
        query = search_topic(message, list(history)) + " beginner guide"
    elif skill == "action":
        query = "how to " + re.sub(r"\b(please|can you|could you|for me)\b", "", message, flags=re.IGNORECASE).strip()
    elif skill not in PERSONAL_SKILLS_NO_SEARCH and (LINK_RE.search(message) or CONCEPT_RE.search(message) or LOOKUP_RE.search(message)
                                                    or is_official_question(message, skill)):
        query = search_topic(message, list(history))
    elif core.needs_search(message):
        query = message
    else:
        return "", [], False
    if place_name and skill in COUNTRY_SEARCH_SKILLS and place_name.lower() not in query.lower():
        query = query[:280] + " " + place_name
    try:
        context, sources = core.search_web(query)
        return context, sources, bool(context)
    except Exception:
        return "", [], False


def enforce_scam_gate(answer, language_code):
    first = answer.strip().split("\n")[0].strip().rstrip(":.").upper()
    if first not in VERDICTS:
        core.log_call({"skill": "scam", "gate": "verdict_missing"})
    official = pick(OFFICIAL_LINES, language_code)
    if official.lower() not in answer.lower():
        answer = answer.rstrip() + "\n\n" + official
        core.log_call({"skill": "scam", "gate": "official_line_added"})
    return answer


# ---------- Dates ----------

def calendar_text(day, days=28):
    """A ready-made calendar, so the model looks dates up instead of calculating them."""
    lines = []
    for i in range(days):
        d = day + timedelta(days=i)
        tag = " (today)" if i == 0 else " (tomorrow)" if i == 1 else ""
        lines.append(f"day +{i}: " + d.strftime("%a %d %b %Y") + tag)
    months = []
    for n in (1, 2, 3, 6, 12):
        y, mth = divmod(day.month - 1 + n, 12)
        try:
            later = day.replace(year=day.year + y, month=mth + 1)
        except ValueError:  # 31 Jan + 1 month: use the last day of February
            later = (day.replace(day=1, year=day.year + y, month=mth + 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        months.append(f"in {n} month{'s' if n > 1 else ''}: " + later.strftime("%a %d %b %Y"))
    return ("Calendar. Look dates up here; never calculate weekdays yourself. To count from a date, add the days to its "
            "day number: \"5 days after\" a date on day +4 is day +9.\n" + "\n".join(lines) + "\n" + "\n".join(months))


TIME_IN_RE = re.compile(r"\btime (is it )?(now )?in ([A-Za-z][A-Za-z .'-]{1,40}?)(\s+(right )?now|\?|$|\s+today)", re.IGNORECASE)
PLACE_ZONES = {"tokyo": "Asia/Tokyo", "london": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin",
               "madrid": "Europe/Madrid", "rome": "Europe/Rome", "jakarta": "Asia/Jakarta", "shanghai": "Asia/Shanghai",
               "los angeles": "America/Los_Angeles", "chicago": "America/Chicago", "kolkata": "Asia/Kolkata",
               "singapore": "Asia/Singapore", "seoul": "Asia/Seoul", "amsterdam": "Europe/Amsterdam", "dublin": "Europe/Dublin",
               "sao paulo": "America/Sao_Paulo", "usa": "America/New_York", "us": "America/New_York", "korea": "Asia/Seoul",
               "uk": "Europe/London", "england": "Europe/London", "india": "Asia/Kolkata", "delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
               "japan": "Asia/Tokyo", "france": "Europe/Paris", "germany": "Europe/Berlin", "spain": "Europe/Madrid", "italy": "Europe/Rome",
               "new york": "America/New_York", "california": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
               "brazil": "America/Sao_Paulo", "indonesia": "Asia/Jakarta", "china": "Asia/Shanghai", "beijing": "Asia/Shanghai",
               "dubai": "Asia/Dubai", "sydney": "Australia/Sydney", "bangalore": "Asia/Kolkata", "bengaluru": "Asia/Kolkata"}


def time_in_place(message):
    """'What time is it in Tokyo?' is worked out from the clock, never from search snippets (they are often old)."""
    m = TIME_IN_RE.search(message)
    if not m:
        return None
    place = m.group(3).strip().lower()
    zone = PLACE_ZONES.get(place)
    try:
        from zoneinfo import ZoneInfo, available_timezones
        if not zone:
            key = place.replace(" ", "_")
            zone = next((z for z in sorted(available_timezones()) if z.split("/")[-1].lower() == key), None)
        if not zone:
            return None
        now = datetime.now(ZoneInfo(zone))
        label = now.strftime("%Z")
    except Exception:
        # No time-zone data on this computer (Windows without tzdata): use the built-in rules.
        now = local_time_fallback(zone)
        if now is None:
            return None
        label = "UTC" + format_offset(now.utcoffset())
    return "In " + m.group(3).strip() + " it is now " + now.strftime("%H:%M on %A %d %B %Y") + " (" + label + ")."


def format_offset(delta):
    minutes = int(delta.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    h, mm = divmod(abs(minutes), 60)
    return f"{sign}{h}" + (f":{mm:02d}" if mm else "")


def _nth_sunday(year, month, n):
    """n-th Sunday of a month (n = -1 for the last), at 00:00 UTC."""
    import calendar as _cal
    days = [d for d in range(1, _cal.monthrange(year, month)[1] + 1) if date(year, month, d).weekday() == 6]
    return datetime(year, month, days[n], tzinfo=timezone.utc)


ZONE_RULES = {  # standard offset in hours, daylight-saving rule
    "Asia/Tokyo": (9, None), "Asia/Kolkata": (5.5, None), "Asia/Jakarta": (7, None), "Asia/Shanghai": (8, None),
    "Asia/Dubai": (4, None), "America/Sao_Paulo": (-3, None), "Asia/Singapore": (8, None), "Asia/Seoul": (9, None),
    "Europe/London": (0, "eu"), "Europe/Paris": (1, "eu"), "Europe/Berlin": (1, "eu"), "Europe/Madrid": (1, "eu"),
    "Europe/Rome": (1, "eu"), "Europe/Amsterdam": (1, "eu"), "Europe/Dublin": (0, "eu"),
    "America/New_York": (-5, "us"), "America/Chicago": (-6, "us"), "America/Denver": (-7, "us"), "America/Los_Angeles": (-8, "us"),
    "Australia/Sydney": (10, "au"),
}


def local_time_fallback(zone, utc_now=None):
    if zone not in ZONE_RULES:
        return None
    utc_now = utc_now or datetime.now(timezone.utc)
    std, rule = ZONE_RULES[zone]
    y, dst = utc_now.year, False
    if rule == "eu":   # last Sunday of March to last Sunday of October, 01:00 UTC
        dst = _nth_sunday(y, 3, -1) + timedelta(hours=1) <= utc_now < _nth_sunday(y, 10, -1) + timedelta(hours=1)
    elif rule == "us":  # second Sunday of March to first Sunday of November, 02:00 local
        dst = (_nth_sunday(y, 3, 1) + timedelta(hours=2 - std) <= utc_now < _nth_sunday(y, 11, 0) + timedelta(hours=1 - std))
    elif rule == "au":  # first Sunday of October to first Sunday of April
        dst = not (_nth_sunday(y, 4, 0) - timedelta(hours=std - 2) <= utc_now < _nth_sunday(y, 10, 0) - timedelta(hours=std - 2))
    offset = timedelta(hours=std + (1 if dst else 0))
    return utc_now.astimezone(timezone(offset))


TIME_GIVEN_RE = re.compile(r"\d{1,2}(:\d{2})?\s*(am|pm)\b|\d{1,2}:\d{2}|\b\d{1,2} to \d{1,2}\b|बजे", re.IGNORECASE)
TEMPLATE_HEAD = {"en": ("Day", "Time", "What", "Notes", "Maths class"), "hi": ("दिन", "समय", "क्या", "नोट", "गणित की क्लास"),
                 "es": ("Día", "Hora", "Qué", "Notas", "Clase de matemáticas"), "fr": ("Jour", "Heure", "Quoi", "Notes", "Cours de maths")}


def schedule_template(language_code, day):
    """A fill-in table, added by code so it is always there (the model sometimes leaves it out)."""
    d, t, w, n, ex = pick(TEMPLATE_HEAD, language_code)
    monday = day + timedelta(days=(7 - day.weekday()) % 7 or 7)
    return f"| {d} | {t} | {w} | {n} |\n|---|---|---|---|\n| {monday.strftime('%a %d %b')} | 10:00–11:00 | {ex} | – |"


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "twenty": 20, "thirty": 30}
_N = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fourteen|twenty|thirty)"
DATE_PHRASE_RE = re.compile(
    r"\b(?P<wd>(next|this|on|by|coming|until) (monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b"
    r"|\b(?P<tom>tomorrow|day after tomorrow)\b"
    r"|\b(?P<rel>(in|within) " + _N + r" (day|week|month|year)s?)\b"
    r"|\b(?P<chain>" + _N + r" (day|week|month)s? (after|later than|from) (that|then|it|this|the first|the hackathon|the first one)|" + _N + r" (day|week|month)s? later)\b"
    r"|(?P<abs>\b\d{1,2}(st|nd|rd|th)?\s+(of\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b"
    r"|\d{1,2}\s*(जनवरी|फ़रवरी|फरवरी|मार्च|अप्रैल|मई|जून|जुलाई|अगस्त|सितंबर|सितम्बर|अक्टूबर|अक्तूबर|नवंबर|नवम्बर|दिसंबर|दिसम्बर))"
    r"|(?P<hiweek>(एक|दो|तीन|चार|पांच|पाँच|\d+)\s*(हफ़्त|हफ्त|सप्ताह)\S*)"
    r"|(?P<himonth>(एक|दो|तीन|चार|छह|छः|\d+)\s*(महीन)\S*)",
    re.IGNORECASE)
MONTHS_EN = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONTHS_HI = ["जनवरी", "फ", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सित", "अक्", "नव", "दिस"]
HI_NUMS = {"एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6}


def add_months(day, n):
    y, m = divmod(day.month - 1 + n, 12)
    y, m = day.year + y, m + 1
    import calendar as _cal
    return day.replace(year=y, month=m, day=min(day.day, _cal.monthrange(y, m)[1]))


def _shift(start, count, unit):
    unit = unit.lower()
    if unit.startswith("day"):
        return start + timedelta(days=count)
    if unit.startswith("week"):
        return start + timedelta(weeks=count)
    if unit.startswith("month"):
        return add_months(start, count)
    return add_months(start, 12 * count)


def resolve_dates(message, day):
    """'next Monday', 'in 3 months', '5 days after that': worked out here, because the model's date arithmetic is unreliable."""
    out, last = [], day
    for m in DATE_PHRASE_RE.finditer(message):
        text = m.group(0)
        words = text.lower().split()
        if m.group("abs"):
            num = int(re.match(r"\d+", text).group(0))
            word = re.sub(r"[\d\s]|st|nd|rd|th|of", "", text.lower(), count=0)
            mon = next((i + 1 for i, k in enumerate(MONTHS_EN) if word.startswith(k)), None)
            if mon is None:
                mon = next((i + 1 for i, k in enumerate(MONTHS_HI) if word.startswith(k)), None)
            if not mon:
                continue
            try:
                found = date(day.year, mon, num)
                if found < day - timedelta(days=60):
                    found = date(day.year + 1, mon, num)   # "13 January" said in December means next year
            except ValueError:
                continue
            last = found
            out.append(f'"{text}" = {last.strftime("%a %d %b %Y")}')
            continue
        if m.group("hiweek") or m.group("himonth"):
            n = re.match(r"(\d+|\S+)", text).group(1)
            count = int(n) if n.isdigit() else HI_NUMS.get(n, 0)
            if not count:
                continue
            last = _shift(day, count, "week" if m.group("hiweek") else "month")
            out.append(f'"{text}" = {last.strftime("%a %d %b %Y")}')
            continue
        if m.group("wd"):
            target = WEEKDAYS.index(words[-1])
            last = day + timedelta(days=(target - day.weekday()) % 7 or 7)
        elif m.group("tom"):
            last = day + timedelta(days=2 if "after" in text.lower() else 1)
        elif m.group("rel"):
            last = _shift(day, int(words[1]) if words[1].isdigit() else NUM_WORDS[words[1]], words[2])
        else:
            last = _shift(last, int(words[0]) if words[0].isdigit() else NUM_WORDS[words[0]], words[1])
        out.append(f'"{text}" = {last.strftime("%a %d %b %Y")}')
    if not out:
        return ""
    return "(Dates worked out by the app, exact: " + "; ".join(out) + ". Use these dates.)"


def time_text():
    now = datetime.now().astimezone()
    utc = datetime.now(timezone.utc)
    return ("Current time: " + now.strftime("%H:%M") + " local (" + now.strftime("%Z, UTC%z") + "), which is "
            + utc.strftime("%H:%M on %a %d %b") + " UTC. For the time in another place, work it out from this UTC time "
            "and that place's time zone (including daylight saving). Never copy a time or date from search results: they are often old.")


def parse_day(today):
    try:
        return datetime.strptime(today, "%Y-%m-%d").date() if today else date.today()
    except ValueError:
        return date.today()


# The person asks to keep something: the page then offers a goal draft to confirm.
SAVE_INTENT_RE = re.compile(
    r"\b(save|put|add|keep|store)\b[^.?!]{0,40}\b(goals?|plan|to-?dos?|list)\b|\bremind me\b"
    r"|लक्ष्य|सेव|सहेज|objectif|ziel|meta|obiettivo|doel|cel\b|目标|目標|목표|tujuan|mục tiêu|hedef|lengo",
    re.IGNORECASE,
)

GOAL_DRAFT_RULES = """You turn a conversation into one goal the person can save. Reply with only JSON inside <answer> and </answer>, like this:
{"title": "Maths project submission", "due": "2026-11-02", "steps": [{"text": "Attend maths class at 10:00", "due": "2026-10-30"}, {"text": "Finish the project draft", "due": "2026-11-01"}, {"text": "Submit the project", "due": "2026-11-02"}]}

Rules:
- title: what the person wants to achieve, at most 8 words, in $language. Not a copy of their message.
- due: the final date in YYYY-MM-DD, or "" if there is none.
- steps: 2 to 6 concrete actions in order, each starting with a verb, in $language. Each has a due date in YYYY-MM-DD or "".
- Make every step specific, using the exact details from the conversation: names, ingredients, amounts, times, places, tools, topics.
  Bad: "Prep the veg and tofu", "Cook quickly", "Practise". Good: "Press 200 g tofu for 10 minutes and cut it into cubes",
  "Stir-fry the broccoli on high heat for 4 minutes", "Shoot 3 ends of 6 arrows at 10 metres".
- Spread the step dates across the time available, in order, from today to the final date; never put every step on the last day,
  and never give a step a date after the final date.
- A task for today (for example cooking a dish tonight) has today as its final date and today for every step.
- Use only what the person said and the plan in the conversation. Never invent appointments, times or tasks.
- Look dates up in the calendar below; do not calculate weekdays yourself."""


def _valid_date(text):
    try:
        datetime.strptime(str(text), "%Y-%m-%d")
        return str(text)
    except ValueError:
        return ""


def spread_step_dates(steps, due, today):
    """Step dates checked in code: if they are missing, all on one day, or after the final date,
    spread them evenly from today to the final date (the first step today, the last on the final date)."""
    if not due or len(steps) < 2:
        return steps
    end = datetime.strptime(due, "%Y-%m-%d").date()
    if end < today:
        return steps
    dates = [st["due"] for st in steps]
    bad = (any(not d for d in dates) or len(set(dates)) == 1
           or any(d > due or d < today.isoformat() for d in dates) or dates != sorted(dates))
    if not bad:
        return steps
    span = (end - today).days
    n = len(steps)
    for i, st in enumerate(steps):
        st["due"] = (today + timedelta(days=(i * span) // (n - 1))).isoformat()
    return steps


def draft_goal(history, language_code=DEFAULT_LANGUAGE, today=None):
    """Ask the model for a structured goal. Returns a dict, or None if no clean draft was produced."""
    if language_code not in LANGUAGE_NAMES:
        language_code = DEFAULT_LANGUAGE
    from string import Template
    system_text = (Template(GOAL_DRAFT_RULES).safe_substitute(language=LANGUAGE_NAMES[language_code])
                   + "\n\n" + calendar_text(parse_day(today)))
    transcript = "\n\n".join(("Person: " if h["role"] == "user" else "Auriv: ") + h["content"] for h in history)
    messages = [{"role": "system", "content": system_text},
                {"role": "user", "content": "Conversation:\n\n" + transcript}]
    for attempt in range(CFG["max_attempts"]):
        response, used_model = create_completion(
            CFG["model"], messages=messages, max_tokens=CFG["max_tokens"], temperature=0.1)
        text = response.choices[0].message.content or ""
        match = re.search(r"\{.*\}", core.extract_answer(text) or text, re.DOTALL)
        core.log_call({"skill": "goal_draft", "model": used_model, "attempt": attempt, "finish_reason": response.choices[0].finish_reason,
                       "parsed": bool(match)})
        if match:
            try:
                raw = json.loads(match.group(0))
                title = str(raw.get("title", "")).strip()[:120]
                steps = [{"text": str(st.get("text", "")).strip()[:200], "due": _valid_date(st.get("due", ""))}
                         for st in raw.get("steps", []) if isinstance(st, dict) and str(st.get("text", "")).strip()][:6]
                if title and steps:
                    due = _valid_date(raw.get("due", ""))
                    return {"title": title, "due": due, "steps": spread_step_dates(steps, due, parse_day(today))}
            except (ValueError, AttributeError, TypeError):
                pass
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "Reply again with only the JSON object inside <answer> tags."}]
    return None


# ---------- Reply tidying (in code, after the model) ----------

# A short opening sentence that introduces Auriv, in any language, is removed unless the person asked its name.
SELF_INTRO_RE = re.compile(r"^\s*[^.!?।。\n]{0,40}\bauriv\b[^.!?।。\n]{0,25}[.!?।。]\s*", re.IGNORECASE)
NAME_ASKED_RE = re.compile(
    r"\b(name|nom|nombre|nome|naam|imię|nama|tên|isim|jina|heißt|heet|called)\b|नाम|নাম|பெயர்|名前|名字|이름",
    re.IGNORECASE)


def feminine_hindi(text):
    """Auriv speaks with a female voice: use feminine first-person forms in Hindi."""
    text = re.sub(r"(सकता|रहा|गया|चाहता|पाता)(\s*)(हूँ|हूं)", lambda m: m.group(1)[:-1] + "ी" + m.group(2) + m.group(3), text)
    text = re.sub(r"(मैं[^।.!?\n]{0,60}?)(सकता|पाता)(?=[\s,।.!?])", lambda m: m.group(1) + m.group(2)[:-1] + "ी", text)
    text = re.sub(r"(ऊँ|ऊं|ूँ|ूं)गा(?=[\s,।.!?]|$)", r"\1गी", text)
    return text


INTRO_WORD_RE = re.compile(
    r"\b(name|nom|nombre|llamo|heiße|heet|nome|chiamo|nazywam|nama|tên|adım|jina|i am|i'm|soy|je suis|ich bin|sono|ik ben|jestem|sou|saya|tôi là|ben|mimi ni)\b"
    r"|नाम|मैं|নাম|আমি|பெயர்|நான்|名前|私は|叫|我是|이름|저는", re.IGNORECASE)


# "app (app)": a bracketed English term that repeats the word before it adds nothing.
DUP_BRACKET_RE = re.compile(r"\b([A-Za-z][A-Za-z\- ]{0,30}?)\s*\(\s*\1\s*\)", re.IGNORECASE)


BRACKET_TERM_RE = re.compile(r"\s?\(([A-Za-z][A-Za-z \-/']{1,30})\)")
FULL_STEPS_RE = re.compile(r"\n+\s*(want the full steps[^\n]*|\(the recipe above includes them\.?\))\s*$", re.IGNORECASE)


def tidy_brackets(answer, limit=5):
    """English terms in brackets: only the first time each appears, and at most five per reply."""
    seen = set()

    def keep(m):
        term = m.group(1).strip().lower()
        if term in seen or len(seen) >= limit:
            return ""
        seen.add(term)
        return m.group(0)
    return BRACKET_TERM_RE.sub(keep, answer)


def tidy_reply(answer, message, language_code):
    answer = DUP_BRACKET_RE.sub(r"\1", answer)
    answer = re.sub(r"(\S{2,})\s*\(\s*\1\s*\)", r"\1", answer)  # "निप्पल (निप्पल)"
    answer = re.sub(r"^\s*नहीं,\s*(मुझे पता है|मैं जानती हूँ)[।.!]?\s*", "", answer)
    # Lightning often opens Hindi replies with "नहीं, ..." ("No, ...") even when nothing was a yes/no question.
    if not re.match(r"^\s*(क्या\s|(is|are|can|do|does|should|will|would)\b)", message, re.I):
        answer = re.sub(r"^\s*नहीं,\s*मुझे (मालूम|पता) नहीं[^।\n]*।\s*", "", answer)
        answer = re.sub(r"^\s*नहीं,\s*", "", answer)
    # Only languages the app can speak are wrapped as practice phrases (Sanskrit pose names are read in Hindi).
    answer = re.sub(r"\{\{(sa|mr|ne)\|", "{{hi|", answer)
    # The person never sees "search results"; the links are simply shown under the reply.
    answer = re.sub(r"^(according to|based on) (the )?(search results|sources)( provided)?,?\s*", "", answer, flags=re.I)
    answer = re.sub(r"^\s*sources?:\s*[^\n]*$", "", answer, flags=re.I | re.M).strip()
    answer = answer[:1].upper() + answer[1:] if answer[:1].islower() else answer
    if lang_prefix(language_code) != "en":
        answer = tidy_brackets(answer)
    # The offer of "the full steps" makes no sense when the full steps are already there.
    if len(re.findall(r"^\s*\d+[.)]", answer, re.M)) >= 4:
        for _ in range(2):
            answer = FULL_STEPS_RE.sub("", answer.rstrip())
    if not NAME_ASKED_RE.search(message):
        m = SELF_INTRO_RE.match(answer)
        # Remove only a real self-introduction, and never the whole reply.
        if m and INTRO_WORD_RE.search(m.group(0)) and len(answer[m.end():].strip()) >= 15:
            answer = answer[m.end():]
    if lang_prefix(language_code) == "hi":
        answer = feminine_hindi(answer)
    return answer.strip()


# ---------- Main entry point ----------

PERSONAL_SKILLS = {"goal_planner", "learning_coach", "task_helper", "schedule"}
HELP_LEVELS = ("direct", "step", "teach")


def handle(message, mode="normal", previous="", language_code=DEFAULT_LANGUAGE, help_level="step",
           skill_override=None, history=None, last_skill=None, goal=None, today=None, country=None, spoken=False):
    if language_code not in LANGUAGE_NAMES:
        language_code = DEFAULT_LANGUAGE
    language_name = LANGUAGE_NAMES[language_code]
    history = history or []
    t_start = time.time()

    skill = route(message, mode)
    # A card or a saved goal can pick a personal skill. Safety gates (emergency, scam) and rephrase always win.
    if skill_override in PERSONAL_SKILLS and mode != "rephrase" and skill not in ("emergency", "scam"):
        skill = skill_override
    # Continuity: a plain follow-up (for example, a list of times) stays with the skill already in use.
    elif (skill == "explain" and last_skill in CONTINUING_SKILLS and history
          and not (CONCEPT_RE.search(message) or LOOKUP_RE.search(message) or TASK_RE.search(message)
                   or LINK_RE.search(message) or NEW_QUESTION_RE.search(message))):
        skill = last_skill
    # Phrase lists are strongest in English. For other languages, a message that would get a general answer is
    # classified by the fast model, so goals, schedules, lessons and message checks work the same in every language.
    if (skill == "explain" and mode != "rephrase" and not skill_override
            and (lang_prefix(language_code) != "en" or re.search(r"[^\x00-\u024F]", message))):
        guessed = classify_intent(message)
        if guessed and guessed != "explain":
            core.log_call({"intent_model": guessed})
            skill = guessed
    core.log_call({"route": skill, "message_chars": len(message), "language": language_code})

    if skill == "delete_data":
        # No model call: the page shows a translated confirmation card.
        return {"answer": "", "fallback": False, "search_used": False, "sources": [], "skill": skill}

    if mode != "rephrase" and IDENTITY_ONLY_RE.search(message):
        # Fixed text: the model's own trained answer about itself is wrong ("made by NVIDIA researchers").
        return {"answer": pick(IDENTITY_TEXTS, language_code), "fallback": False, "search_used": False,
                "sources": [], "skill": "explain"}

    if skill == "emergency":
        answer = pick(EMERGENCY_TEXTS, language_code)
        numbers = emergency_numbers(country)
        if numbers:
            answer += "\n\n📞 " + "  ·  ".join(numbers)
        return {"answer": answer, "fallback": False, "search_used": False, "sources": [], "skill": skill}

    system_text = core.load_prompt("system") + "\n\n" + core.load_prompt("language", language=language_name)
    level = help_level if help_level in HELP_LEVELS else "step"
    if skill not in ("scam", "overwhelm"):
        system_text += "\n\n" + core.load_prompt(f"helplevel/{level}")
    day = parse_day(today)
    place = COUNTRY_INFO.get(country, (None,))[0]
    if IDENTITY_ASKED_RE.search(message):
        system_text += "\n\n" + IDENTITY_FACTS
    for upd_country, upd_re, upd_text in FACT_UPDATES:
        if (country or LANGUAGE_COUNTRY.get(language_code)) == upd_country and upd_re.search(message):
            system_text += "\n\nChecked recent change (overrides anything you remember): " + upd_text
    city_time = time_in_place(message)
    if city_time:
        system_text += "\n\nWorked out by the app, exact: " + city_time + " Give this time and day in one sentence."
    if place:
        system_text += ("\n\nThe person lives in " + place + ". When rules, services, prices, websites or phone numbers "
                        "differ between countries, give the ones for " + place + ".")
    system_text += "\n\n" + calendar_text(day) + "\n" + time_text()
    if goal and skill in ("goal_planner", "schedule", "task_helper", "guide_step"):
        system_text += (
            "\n\nThe person chose to continue a goal they saved: \"" + goal["title"] + "\". "
            "Steps they have marked done: " + str(goal["steps_done"]) + ". "
            "Last recorded next step: \"" + (goal["next_step"] or "not set") + "\". "
            "Build on this progress. Do not start the plan again from the beginning."
        )

    if skill == "rephrase":
        user_text = core.load_prompt("rephrase", previous=previous, question=message)
        context, sources, search_used = "", [], False
    else:
        extra = skill_prompt(skill)
        if extra:
            system_text += "\n\n" + extra
        user_text = message
        if spoken:
            user_text += ("\n\n(This message was spoken and turned into text automatically, so some words may be misheard. "
                          "Work out what the person meant from the context and answer that. Do not mention the misheard words.)")
        if skill == "learning_coach" and wants_place_lesson(message + " " + " ".join(h["content"] for h in history[-4:] if h["role"] == "user")):
            user_text += ("\n\n(This is a lesson about the place or culture itself, not its language. Do not include any language "
                          "phrases, {{..}} practice phrases, word-by-word lines or pronunciation, now or in the 'Next' line. "
                          "For Practice, ask one short question about what was taught.)")
        if skill == "learning_coach" and last_skill != "learning_coach" and (TEACH_RE.search(message) or WANT_LEARN_RE.search(message)):
            user_text += ("\n\n(This is a request for a lesson. Say yes and start Lesson 1 now. Write the explanations in "
                          + language_name + "; only the practice phrases are in the language being learned.)")
        dates = resolve_dates(message, day) if skill != "scam" else ""
        if dates:
            user_text += "\n\n" + dates
        if skill == "task_helper" and WRITE_RE.search(message):
            user_text += ("\n\n(Use [square brackets] for every detail I have not told you, such as my address or flat number, "
                          "since when, error codes, what I have tried, or my reason. Do not make any of these up.)")
        if skill == "goal_planner":
            user_text += "\n\n(Do not assume any amount, price or number I have not told you. Use a placeholder like [price] instead.)"
        if skill == "learning_coach" and last_skill == "learning_coach" and not message.lower().startswith("i heard"):
            user_text += ("\n\n(Continue the lesson with something new that has not been taught yet in this conversation. "
                          "Do not repeat earlier phrases, and do not ask a question you already asked.)")
        if skill == "task_helper" and WRITE_RE.search(message):
            system_text += ("\n\nThis is a writing request. Write the full draft now, ready to copy, with a subject line for an email. "
                            "Use [square brackets] for every detail you do not know (names, dates, readings, what was tried). "
                            "Never add facts the person did not give. After the draft, add at most two short lines: one tip, "
                            "and a reminder to read it before sending.")
        recent = " ".join([message] + [h["content"] for h in history[-2:] if h["role"] == "user"])
        cooking = skill in ("learning_coach", "explain", "task_helper") and COOKING_RE.search(recent)
        hands_on = (not cooking and skill in ("learning_coach", "explain") and HANDS_ON_RE.search(recent)
                    and not OFFICIAL_Q_RE.search(message) and not LICENCE_RE.search(message))
        if cooking:
            try:
                context, sources = core.search_web(search_topic(message, history) + " recipe", allow_video=True)
                sources, search_used = rank_sources(sources, language_code, country), bool(context)
            except Exception:
                context, sources, search_used = "", [], False
            system_text += ("\n\nThis is a cooking question. Give the recipe directly: a short line on what it is, "
                            "a bold heading for the ingredients (in the reply language) with amounts (say how many people it serves), **Steps** as a numbered list with times "
                            "and heat level (also under a bold heading in the reply language), and one food-safety tip. Put each ingredient on its own line as a list, and each step on its own numbered line. Use ingredients easy to find in the person's country. "
                            "End with one short line saying that recipe pages and videos are linked below. Do not offer to expand the recipe.")
        elif city_time:
            context, sources, search_used = "", [], False  # worked out from the clock; search snippets are often old
        elif hands_on:
            context, sources, search_used = hands_on_search(message, history, language_code, country)
            system_text += ("\n\nThis is a hands-on skill. You cannot watch the person, so: give the basics in words, "
                            "a short beginner practice plan, one safety tip, and suggest a local club, class or coach. "
                            "Say that the videos and guides shown under your reply let them see the technique.")
        else:
            context, sources, search_used = gather_sources(message, skill, language_code, history, country)
        if context:
            user_text += "\n\n" + core.load_prompt("search_context", results=context)

    # Decide now whether the page will offer a goal draft, and tell the model, so it never promises one that is not shown.
    offer_save = bool(SAVE_INTENT_RE.search(message)) and skill not in ("scam", "emergency", "rephrase")
    system_text += ("\n\nA goal draft will be shown under your reply for the person to check and save. Mention it in one short line at the end."
                    if offer_save else
                    "\n\nDo not mention goal drafts or saving in this reply.")
    t_model = time.time()
    # The scam check looks at the pasted message only, never earlier conversation.
    chosen_model = model_for(skill, message, language_code)
    if lang_prefix(language_code) != "en":
        user_text += "\n\n(Reply in " + language_name + ".)"
    answer, fallback = call_model(system_text, user_text, skill, [] if skill == "scam" else history, chosen_model, message,
                                  language_code=language_code)

    if (not fallback and not search_used and skill not in PERSONAL_SKILLS_NO_SEARCH
            and skill != "rephrase" and UNSURE_RE.search(answer)):
        context, sources, search_used = search_now(search_topic(message, history), language_code, country)
        if context:
            core.log_call({"skill": skill, "unsure_search": True})
            answer2, fallback2 = call_model(
                system_text, message + "\n\n" + core.load_prompt("search_context", results=context), skill, history, chosen_model, message,
                language_code=language_code)
            if not fallback2:
                answer = answer2

    if not fallback and skill not in ("scam", "emergency"):
        answer = tidy_reply(answer, message, language_code)
    if not fallback and skill == "schedule" and "|" not in answer and not TIME_GIVEN_RE.search(message):
        answer = answer.rstrip() + "\n\n" + schedule_template(language_code, day)

    if skill == "scam" and not fallback:
        answer = enforce_scam_gate(answer, language_code)
        report = scam_report_line(country, language_code)
        first_route = re.split(r"[ ,·(]", report.split(": ", 1)[1])[0] if report else ""
        if report and first_route not in answer:
            answer += "\n\n" + report
    elif skill == "scam" and fallback:
        # Never show the generic "what is on your mind" reply for a message check.
        # Treat the message as suspicious, and give the official-channel rule.
        answer = SCAM_FALLBACK + "\n\n" + pick(OFFICIAL_LINES, language_code)

    core.log_call({"timing": {"skill": skill, "model": chosen_model.split("/")[-1], "search_used": search_used,
                              "search_s": round(t_model - t_start, 1), "model_s": round(time.time() - t_model, 1),
                              "total_s": round(time.time() - t_start, 1)}})
    offer_save = offer_save and not fallback
    return {"answer": answer, "fallback": fallback, "search_used": search_used,
            "sources": sources, "skill": skill, "offer_save": offer_save}


# ---------- Route tests (English, no model calls) ----------

ROUTE_TESTS = [
    ("I received this message and want to check it. Here it is:", "scam"),
    ("Your account is blocked, click http://example.com to verify", "scam"),
    ("can you pay this bill for me", "action"),
    ("I don't understand", "clarify"),
    ("I'm stuck on step 2", "guide_step"),
    ("my cat isn't eating", "professional"),
    ("what does interest on a loan mean", "professional"),
    ("help me understand what a password is", "explain"),
    ("someone is hurt and not breathing", "emergency"),
    ("what is the equation of a circle with radius 3", "explain"),
    ("what is the best way to organise my assignments", "research"),
    ("which is better for revising, flashcards or practice tests", "research"),
    ("I have lots to do and feel confused", "overwhelm"),
    ("I don't know where to start", "overwhelm"),
    ("I have a lot of meetings and classes", "schedule"),
    ("help me organise my schedule for next week", "schedule"),
    ("how do i join a meeting on zoom", "explain"),
    ("save my meeting goal", "explain"),
    ("CLEAR ALL DATA OF MINE", "delete_data"),
    ("क्या तुम मुझे सिखा सकती हो", "learning_coach"),
    ("can you teach me English", "learning_coach"),
    ("can you teach me badminton", "learning_coach"),
    ("can you teach me to cook dal", "learning_coach"),
    ("please delete all my data", "delete_data"),
    ("how do I delete my Facebook account", "explain"),
    ("on Monday I have a hackathon deadline, then after 5 days another deadline, then a week for my research", "schedule"),
    ("my exam is on Monday", "explain"),
    ("I want to work on a simple Python machine learning project in this one week, that's my deadline", "goal_planner"),
    ("I want to learn Spanish", "learning_coach"),
    ("hi can you help me to learn Hindi", "learning_coach"),
]


if __name__ == "__main__":
    passed = 0
    for text, expected in ROUTE_TESTS:
        got = route(text)
        ok = got == expected
        passed += ok
        print(("PASS" if ok else "FAIL"), f"| expected {expected:<12} got {got:<12} | {text}")
    print(f"\n{passed}/{len(ROUTE_TESTS)} routing tests passed")
