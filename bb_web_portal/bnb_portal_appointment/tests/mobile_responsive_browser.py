"""Local neutralized preview only. No checkout submissions or real card entry.
Run: python tests/mobile_responsive_browser.py --out <artifact dir>
Requires Playwright and a running restored preview with this ticket's views.
"""
import argparse,json,time
from pathlib import Path
from lxml import etree
from playwright.sync_api import sync_playwright
parser=argparse.ArgumentParser()
parser.add_argument('--base',default='http://127.0.0.1:8095')
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--engine',choices=['chromium','webkit'],default='chromium')
parser.add_argument('--short-only',action='store_true')
args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
addon=Path(__file__).resolve().parents[2]
wallet_source=(addon/'payment_nab_gateway/static/src/js/nab_payment_form.js').read_text()
challenge=wallet_source[wallet_source.index('    _nabChallenge(enrolment) {'):wallet_source.index('    async _processDirectFlow')].rstrip().rstrip(',')
inline=etree.parse(str(addon/'payment_nab_gateway/views/payment_nab_gateway_templates.xml')).find("template[@id='inline_form']")
for element in inline.iter():
 for key in list(element.attrib):
  if key.startswith('t-'):del element.attrib[key]
inline_html=''.join(etree.tostring(child,encoding='unicode',method='html') for child in inline)
fixture=json.loads((args.out/'checkout_fixture.json').read_text())
metrics_js='''()=>{
 const w=innerWidth,scope=document.querySelector('#fresha-booking-steps')||document.querySelector('.salon-checkout-wrapper')||document.querySelector('#wrapwrap');
 const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility==='visible'&&!e.closest('.offcanvas:not(.show)');};
 const overflow=[...scope.querySelectorAll('*')].filter(visible).filter(e=>{const r=e.getBoundingClientRect();return r.right>w+2&&r.left<w&&!e.closest('.service-categories-tabs,.fresha-dates-row,.fresha-breadcrumb,.carousel');}).map(e=>e.id||e.className);
 const controls=[...scope.querySelectorAll('button,input:not([type=hidden]):not([type=radio]):not([type=checkbox]),select')].filter(visible);
 return {overflow,small:controls.filter(e=>e.getBoundingClientRect().height<43).map(e=>e.id||e.className),font:controls.filter(e=>e.matches('input,select')&&parseFloat(getComputedStyle(e).fontSize)<16).map(e=>e.id),scrollWidth:document.documentElement.scrollWidth,width:w};
}'''
# Cache the core disabled-notifications response in this test browser only.
# This avoids unrelated push requests being interrupted by rapid test navigation.
disabled_push_script="localStorage.setItem('social_push_notifications.notification_request_config',JSON.stringify({expirationDate:new Date(Date.now()+86400000).toISOString()}))"
results=[]; errors=[]; pending={}
def record(page,name,width,mobile=True):
 m=page.evaluate(metrics_js);results.append({'page':name,'viewport':width,**m})
 assert not m['overflow'],(name,width,'clipped elements',m['overflow'])
 assert m['scrollWidth']<=width,(name,width,'horizontal overflow')
 if mobile:
  assert not m['small'],(name,width,'small controls',m['small'])
  assert not m['font'],(name,width,'small form text',m['font'])
def settle(page):
 page.wait_for_timeout(350)
 deadline=time.monotonic()+10
 while pending.get(id(page)) and time.monotonic()<deadline:page.wait_for_timeout(100)
 assert not pending.get(id(page)), 'Preview requests did not settle before navigation'
def go(page,path,booking=False):
 settle(page)
 page.goto(args.base+path,wait_until='domcontentloaded')
 if booking:page.wait_for_function('!!window.bnbMobileBookingController')
 else:page.wait_for_load_state('load')
 settle(page)
def show(page,step):
 page.evaluate('''step=>{for(const el of document.getElementById('fresha-booking-steps').children)el.style.display=el.id==='step-'+step?'block':'none';}''',step)
 page.wait_for_timeout(80)
with sync_playwright() as p:
 browser=getattr(p,args.engine).launch(headless=True)
 for width,height in ([] if args.short_only else [(320,740),(360,800),(390,844),(430,932),(768,1024),(820,1180),(1024,768),(1440,1000)]):
  page=browser.new_page(viewport={'width':width,'height':height})
  page.add_init_script(disabled_push_script)
  pending[id(page)]=set()
  page.on('request',lambda request,pg=page:pending[id(pg)].add(request) if request.resource_type in ('fetch','xhr') else None)
  page.on('requestfinished',lambda request,pg=page:pending[id(pg)].discard(request))
  page.on('requestfailed',lambda request,pg=page:pending[id(pg)].discard(request))
  page.on('pageerror',lambda error:errors.append(str(error)))
  page.on('console',lambda message:errors.append(message.text) if message.type=='error' and '[Online Booking]' in message.text else None)
  go(page,'/book-online',True);record(page,'location',width,width<=1024)
  assert page.locator('#bookingMobileActions').is_hidden()
  page.locator('.location-salon-card').first.click()
  page.wait_for_url('**/book-online?branch_id=*',wait_until='domcontentloaded')
  page.wait_for_function('!!window.bnbMobileBookingController')
  for step in ['service','date','beautician','customer','payment']:
   show(page,step)
   if step=='beautician':
    page.evaluate("window.beauticianHandler.render([{id:99999,name:'Professional with a very long descriptive name',image:'data:image/svg+xml,%3Csvg xmlns=\"http://www.w3.org/2000/svg\"/%3E',price:'$10.00'}], [], '', true, false)")
   record(page,step,width,width<=1024)
   assert page.locator('#bookingMobileContinue').is_visible()==(width<=1024)
   assert page.locator('[id=step-'+step+']').count()==1
   if width in (320,390,820):page.screenshot(path=str(args.out/f'{args.engine}_{step}_{width}.png'))
  show(page,'service')
  if width<=1024:
   page.locator('#bookingMobileContinue').click()
   assert page.locator('#bookingAvailabilityPopup').is_visible()
   assert 'select at least one service' in page.locator('#bookingAvailabilityPopup').inner_text().lower()
   page.locator('.booking-availability-popup-close').click()
   page.evaluate("document.querySelector('#step-service .service-continue-btn').disabled=true")
   page.wait_for_timeout(40);assert page.locator('#bookingMobileContinue').is_disabled()
  go(page,'/custom-home');record(page,'home',width,width<=1024)
  if width<=1024:
   page.get_by_role('button',name='Toggle navigation').click()
   page.wait_for_timeout(400)
   assert page.locator('#top_menu_collapse_mobile').is_visible()
   assert page.locator('#top_menu_collapse_mobile').bounding_box()['width']<=width
   page.get_by_role('button',name='Close',exact=True).click()
  go(page,'/gift-voucher');record(page,'gift voucher',width,width<=1024)
  go(page,fixture['checkout']);record(page,'secure checkout (providers disabled)',width,width<=1024)
  # Layout fixture uses the real inline template; external gateway remains disabled.
  page.evaluate('(markup)=>document.querySelector("#salon_payment_method").innerHTML=markup',inline_html)
  record(page,'card fields (layout fixture)',width,width<=1024)
  if width<=1024:
   month=page.locator('#nab-expiry-month').bounding_box();year=page.locator('#nab-expiry-year').bounding_box();cvv=page.locator('#nab-card-cvv-container').bounding_box()
   assert abs(month['y']-year['y'])<2 and cvv['y']>month['y']+month['height']
   assert page.locator('#nab-card-number-container').bounding_box()['height']>=48
  if width==390:page.screenshot(path=str(args.out/f'{args.engine}_checkout_390.png'))
  go(page,fixture['result']);record(page,'payment result',width,width<=1024)
  settle(page)
  page.close()
  print(args.engine,'viewport',width,'passed',flush=True)
 page=browser.new_page(viewport={'width':390,'height':320})
 page.add_init_script(disabled_push_script)
 go(page,'/book-online?branch_id=3',True)
 page.evaluate("window.bnbShowBookingError('A long booking message. '.repeat(100))")
 page.locator('.booking-availability-popup-card').evaluate('e=>Promise.all(e.getAnimations().map(a=>a.finished))')
 popup=page.locator('.booking-availability-popup-card');rect=popup.bounding_box()
 assert rect['y']>=0 and rect['y']+rect['height']<=320
 assert popup.evaluate('e=>e.scrollHeight>e.clientHeight')
 assert page.locator('.booking-availability-popup-close').bounding_box()['height']>=44
 page.locator('.booking-availability-popup-close').click()
 # Real service details and related-services renderers on a short viewport.
 page.locator('.service-item-card').first.evaluate("e=>e.dataset.serviceDescription='Sample service description. '.repeat(100)")
 page.locator('.service-details-btn').first.click()
 page.locator('.service-modal-content').evaluate('e=>Promise.all(e.getAnimations().map(a=>a.finished))')
 detail=page.locator('.service-modal-content').bounding_box()
 assert detail['y']>=0 and detail['y']+detail['height']<=320
 page.locator('.service-modal-close').click()
 page.evaluate("window.relatedServicesHandler.showModalDirectly({related_services:Array.from({length:10},(_,i)=>({id:i+1,name:'Sample additional service with a descriptive name',formatted_total_price:'$10.00',duration:0.25,duration_display:'15 minutes',addon_price:0}))})")
 page.locator('.related-services-modal-content').evaluate('e=>Promise.all(e.getAnimations().map(a=>a.finished))')
 related=page.locator('.related-services-modal-content').bounding_box()
 assert related['y']>=0 and related['y']+related['height']<=320, related
 footer=page.locator('.related-modal-footer').bounding_box()
 assert footer['y']+footer['height']<=320
 assert page.locator('.related-modal-body').evaluate('e=>e.scrollHeight>e.clientHeight')
 page.get_by_role('button',name='Close extra services',exact=True).click()
 # Run the actual bank challenge method, replacing only outbound submission.
 page.evaluate('''method=>{window._t=text=>text;window.layoutBank={_nabPostToFrame(){},...eval('({'+method+'})')};window.bankCancelled=false;layoutBank._nabChallenge({}).then(value=>window.bankCancelled=value===null);}''',challenge)
 iframe=page.locator('iframe[name="nab-bank-challenge"]');box=iframe.bounding_box()
 assert box['x']>=0 and box['y']>=0 and box['x']+box['width']<=390 and box['y']+box['height']<=320
 assert iframe.get_attribute('title')=='Bank payment verification'
 page.get_by_role('button',name='Cancel',exact=True).click()
 page.wait_for_function('window.bankCancelled===true')
 settle(page)
 results.append({'page':'short-screen popup and bank challenge','viewport':'390x320','passed':True})
 browser.close()
assert not errors,errors
(args.out/f'{args.engine}_{"short" if args.short_only else "responsive"}_results.json').write_text(json.dumps({'checks':len(results),'errors':errors,'results':results},indent=2))
print(len(results),'layout checks passed; no booking JavaScript errors.')
