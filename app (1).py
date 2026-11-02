import os, re, time, urllib.parse
from collections import defaultdict, deque
import requests, yt_dlp
from flask import Flask, request, jsonify, render_template, Response, abort

app = Flask(__name__, template_folder=".")
E = os.getenv
CTX = dict(site=E("SITE_NAME", "ReelSave"), ad_head=E("AD_HEAD_CODE", ""), ad_slot=E("AD_SLOT_CODE", ""), ad_social=E("AD_SOCIAL_CODE", ""), ad_gate=E("AD_GATE_CODE", ""),
           gate=int(E("GATE_SECONDS", "8")), domain=E("DOMAIN", "").rstrip("/"))
COOKIES = "/tmp/cookies.txt"
if E("IG_COOKIES"):
    open(COOKIES, "w").write(E("IG_COOKIES"))

T = "Download Instagram {} - Free, No Watermark"
PAGES = {
 "": dict(h1="Instagram Video Downloader", title="Instagram Video Downloader - Download Reels, Photos & DP (No Watermark)",
          desc="Free Instagram video downloader. Paste a public link and save reels, videos, photos and profile pictures in HD without watermark.", lang="en",
          text="Paste the link of any public Instagram reel, video or photo, press Download, watch a short ad and the file is saved to your gallery in original quality. Works on Android, iPhone and PC. No app or login needed."),
 "reels-downloader": dict(h1="Instagram Reels Downloader", title=T.format("Reels"), desc="Save Instagram reels in HD to your phone. Paste the reel link and download free.", lang="en",
          text="Copy the reel link from Instagram (Share, then Copy link), paste it above and download the reel as an MP4 file in original quality."),
 "video-downloader": dict(h1="Instagram Video Downloader", title=T.format("Videos"), desc="Download Instagram videos online free in HD MP4.", lang="en",
          text="Download any public Instagram video as MP4. No watermark, no signup."),
 "photo-downloader": dict(h1="Instagram Photo Downloader", title=T.format("Photos"), desc="Download Instagram photos and carousel posts in full quality.", lang="en",
          text="Paste a public post link and save every photo of a post or carousel in full resolution."),
 "profile-picture-downloader": dict(h1="Instagram Profile Picture Downloader", title=T.format("Profile Pictures (DP)"), desc="View and download Instagram DP in full size.", lang="en",
          text="Paste the profile link, for example instagram.com/username, to save the profile picture in the biggest size available."),
 "bangla": dict(h1="ইনস্টাগ্রাম রিল ও ভিডিও ডাউনলোড", title="ইনস্টাগ্রাম রিল ডাউনলোড - ফ্রি, ওয়াটারমার্ক ছাড়া", desc="ইনস্টাগ্রাম রিল, ভিডিও, ছবি ও প্রোফাইল পিক ফ্রিতে ডাউনলোড করুন।", lang="bn",
          text="পাবলিক ইনস্টাগ্রাম রিল বা ভিডিওর লিংক পেস্ট করুন, ডাউনলোডে চাপ দিন, একটি ছোট বিজ্ঞাপন দেখুন, তারপর ফাইল আপনার গ্যালারিতে সেভ হবে।"),
}
LEGAL = {
 "privacy": ("Privacy Policy", "We do not store the links you paste or the files you download. Ad partners may use cookies to show ads. We may keep basic server logs for security. Contact us for any privacy request."),
 "terms": ("Terms of Use", "Use this service only for content you own or have permission to download. We are not affiliated with Instagram or Meta. You are responsible for how you use downloaded content."),
 "dmca": ("DMCA / Copyright", "If you are a copyright owner and want content or access blocked, contact us with the link and proof of ownership and we will act promptly."),
}

def mk(slug):
    return lambda: render_template("index.html", p=PAGES[slug], slug=slug, pages=PAGES, **CTX)
for s in PAGES:
    app.add_url_rule("/" + s, "p_" + (s or "home"), mk(s))

@app.get("/<name>")
def legal(name):
    if name not in LEGAL: abort(404)
    return render_template("page.html", title=LEGAL[name][0], body=LEGAL[name][1], **CTX)

@app.get("/robots.txt")
def robots():
    return Response(f"User-agent: *\nAllow: /\nSitemap: {CTX['domain']}/sitemap.xml\n", mimetype="text/plain")

@app.get("/ads.txt")
def ads():
    return Response(E("ADS_TXT", ""), mimetype="text/plain")

@app.get("/sitemap.xml")
def sitemap():
    u = "".join(f"<url><loc>{CTX['domain']}/{s}</loc></url>" for s in list(PAGES) + list(LEGAL))
    return Response(f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{u}</urlset>', mimetype="application/xml")

hits = defaultdict(deque)
def limited():
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0]
    q, now = hits[ip], time.time()
    while q and now - q[0] > 60: q.popleft()
    q.append(now)
    return len(q) > 12

IG = re.compile(r"^https?://(www\.)?instagram\.com/", re.I)
PROFILE = re.compile(r"^https?://(www\.)?instagram\.com/([A-Za-z0-9._]+)/?(\?.*)?$", re.I)
SKIP = {"p", "reel", "reels", "tv", "stories", "explore", "accounts"}

def profile_pic(user):
    import instaloader
    p = instaloader.Profile.from_username(instaloader.Instaloader(quiet=True).context, user)
    return [dict(url=p.profile_pic_url, thumb=p.profile_pic_url, ext="jpg", kind="photo", title=user)]

def media(url):
    m = PROFILE.match(url)
    if m and m.group(2).lower() not in SKIP:
        return profile_pic(m.group(2))
    o = {"quiet": True, "skip_download": True, "format": "best"}
    if os.path.exists(COOKIES): o["cookiefile"] = COOKIES
    with yt_dlp.YoutubeDL(o) as y:
        info = y.extract_info(url, download=False)
    items = []
    for e in (info.get("entries") or [info]):
        if not e or not e.get("url"): continue
        ext = e.get("ext", "mp4")
        items.append(dict(url=e["url"], thumb=e.get("thumbnail"), ext=ext, title=(e.get("title") or "instagram")[:50],
                          kind="photo" if ext in ("jpg", "jpeg", "png", "webp") else "video"))
    return items

@app.post("/api/info")
def info():
    if limited(): return jsonify(error="Too many requests. Wait a minute."), 429
    url = ((request.get_json(silent=True) or {}).get("url") or "").strip()
    if not IG.match(url): return jsonify(error="Please paste a valid Instagram link."), 400
    try:
        items = media(url)
    except Exception:
        return jsonify(error="Could not fetch. The post may be private or Instagram blocked the request. Try again later."), 502
    if not items: return jsonify(error="No downloadable media found."), 404
    return jsonify(items=items)

OK = ("cdninstagram.com", "fbcdn.net")
@app.get("/api/dl")
def dl():
    u = request.args.get("u", ""); h = urllib.parse.urlparse(u).hostname or ""
    if not u.startswith("https://") or not any(h == d or h.endswith("." + d) for d in OK): abort(400)
    r = requests.get(u, stream=True, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    hd = {"Cache-Control": "private, max-age=600"}
    if not request.args.get("inline"):
        n = re.sub(r"[^A-Za-z0-9_.-]", "_", request.args.get("n", "download"))[:60]
        hd["Content-Disposition"] = f'attachment; filename="{n}"'
    return Response(r.iter_content(65536), content_type=r.headers.get("Content-Type", "application/octet-stream"), headers=hd)
