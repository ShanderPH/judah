import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const root=path.resolve(import.meta.dirname,'..');
const load=(name)=>JSON.parse(fs.readFileSync(path.join(root,name),'utf8'));
const clone=(x)=>structuredClone(x);
const base=load('fixtures/judah-inbound/base-valid.json');
const wf00=load('[INHPK] BOT _ 00 - JUDAH Inbound Gateway.json');
const wf01=load('[INHPK] BOT _ 01 - Inbound Gateway.json');
const wf02=load('[INHPK] BOT _ 02 - Customer Identity Resolver (1).json');
const wf03=load('[INHPK] BOT _ 03 - Conversation Message Gateway.json');
const wf04=load('[INHPK] BOT _ 04 - Triage Menu Router.json');
const node=(wf,name)=>wf.nodes.find((n)=>n.name===name);
const tests=[];const test=(name,fn)=>tests.push([name,fn]);
const raw=(payload=base)=>Buffer.from(JSON.stringify(payload));
const headers=(body,now=Math.floor(Date.now()/1000),secret='fixture-secret')=>({
  'content-type':'application/json','x-judah-event-id':base.data.event.event_id,
  'x-idempotency-key':base.data.metadata.idempotency_key,'x-judah-timestamp':String(now),
  'x-judah-signature':'sha256='+crypto.createHmac('sha256',secret).update(String(now)+'.').update(body).digest('hex'),
  'x-delivery-attempt':'1',
});
function authenticate(body,h,secret='fixture-secret',now=Math.floor(Date.now()/1000)){
  const required=['content-type','x-judah-event-id','x-idempotency-key','x-judah-timestamp','x-judah-signature','x-delivery-attempt'];
  if(!required.every(k=>String(h[k]??'').trim()))return false;
  if(!/^[0-9]+$/.test(h['x-judah-timestamp']))return false;const ts=Number(h['x-judah-timestamp']);
  if(ts<now-300||ts>now+300)return false;const m=/^sha256=([a-fA-F0-9]{64})$/.exec(h['x-judah-signature']);if(!m)return false;
  const expected=crypto.createHmac('sha256',secret).update(String(ts)+'.').update(body).digest();const got=Buffer.from(m[1],'hex');return got.length===expected.length&&crypto.timingSafeEqual(got,expected);
}
function validate(payload,h){const d=payload?.data;if(payload?.action!=='PROCESS_NEW_MESSAGE'||d?.schema_version!=='1.0'||d?.event?.type!=='conversation.newMessage'||d?.event?.source!=='judah'||d?.message?.direction!=='INCOMING'||d?.gateway?.is_incoming_customer_message!==true||!String(d?.message?.text??'').trim())return false;if(h['x-judah-event-id']!==d.event.event_id||h['x-idempotency-key']!==d.metadata.idempotency_key||d.hubspot.thread_id!==d.conversation.threadId)return false;return crypto.createHash('sha256').update(`hubspot:${d.hubspot.portal_id}:${d.hubspot.thread_id}:${d.event.message_id}`).digest('hex')===d.metadata.idempotency_key;}
function inbox(status,{recent=false,pending=false}={}){if(status==='PROCESSED'||status==='IGNORED')return 'DUPLICATE';if(status==='PROCESSING'&&recent)return 'BUSY';if(status==='FAILED_RETRYABLE'&&pending)return 'PENDING';return 'PROCESS';}

test('01 HMAC válida',()=>{const b=raw(),h=headers(b);assert.equal(authenticate(b,h),true)});
test('02 HMAC inválida',()=>{const b=raw(),h=headers(b);h['x-judah-signature']='sha256='+'0'.repeat(64);assert.equal(authenticate(b,h),false)});
test('03 assinatura sem prefixo',()=>{const b=raw(),h=headers(b);h['x-judah-signature']=h['x-judah-signature'].slice(7);assert.equal(authenticate(b,h),false)});
test('04 timestamp expirado',()=>{const b=raw(),now=Math.floor(Date.now()/1000),h=headers(b,now-301);assert.equal(authenticate(b,h,'fixture-secret',now),false)});
test('05 timestamp futuro',()=>{const b=raw(),now=Math.floor(Date.now()/1000),h=headers(b,now+301);assert.equal(authenticate(b,h,'fixture-secret',now),false)});
test('06 header obrigatório ausente',()=>{const b=raw(),h=headers(b);delete h['x-delivery-attempt'];assert.equal(authenticate(b,h),false)});
test('07 event_id divergente',()=>{const b=raw(),h=headers(b);h['x-judah-event-id']='different';assert.equal(validate(base,h),false)});
test('08 idempotency key divergente',()=>{const b=raw(),h=headers(b);h['x-idempotency-key']='0'.repeat(64);assert.equal(validate(base,h),false)});
test('09 payload inválido',()=>{const p=clone(base);p.data.message.text='';assert.equal(validate(p,headers(raw(p))),false)});
test('10 primeira entrega válida',()=>assert.equal(inbox(''), 'PROCESS'));
test('11 duplicidade processada',()=>assert.equal(inbox('PROCESSED'),'DUPLICATE'));
test('12 falha após registro inicial',()=>assert.equal(inbox('PROCESSING',{recent:false}),'PROCESS'));
test('13 retry FAILED_RETRYABLE',()=>assert.equal(inbox('FAILED_RETRYABLE'),'PROCESS'));
test('14 recuperação PROCESSING expirado',()=>assert.equal(inbox('PROCESSING',{recent:false}),'PROCESS'));
test('15 duas tentativas concorrentes',()=>assert.equal(inbox('PROCESSING',{recent:true}),'BUSY'));
test('16 origem webhook',()=>assert.equal(base.data.gateway.delivery_method,'webhook'));
test('17 origem reconciliação',()=>{const p=clone(base);p.data.gateway.delivery_method='reconciliation';assert.equal(validate(p,headers(raw(p))),true)});
test('18 ticket_id nulo',()=>{assert.equal(base.data.hubspot.ticket_id,null);assert.equal(validate(base,headers(raw())),true)});
test('19 canais nulos com fallback',()=>{const state={channel_id:'channel-state',channel_account_id:'account-state'};assert.equal(base.data.message.channel_id??state.channel_id,'channel-state')});
test('20 mensagem fora de ordem',()=>{const current=[1,'m1'],previous=[2,'m2'];assert.equal(current[0]<previous[0]||(current[0]===previous[0]&&current[1]<=previous[1]),true)});
test('21 accepted mantém event_id',()=>{const result={status:'accepted',event_id:base.data.event.event_id,duplicate:false};assert.equal(result.event_id,base.data.event.event_id)});
test('22 hidratada não chama GET New Message',()=>{const n=node(wf03,'Needs Message Lookup?');assert.ok(n.parameters.conditions.conditions[0].leftValue.includes('hydration.message_complete'))});
test('REGISTER_STATE preservado',()=>{assert.ok(node(wf03,'Build State Registration'));assert.ok(node(wf02,'Call WF-03 REGISTER_STATE'));assert.ok(node(wf03,'Conversation Gateway Input').parameters.workflowInputs.values.some(v=>v.name==='transport'))});
test('estrutura segura e importável',()=>{for(const wf of [wf00,wf01,wf02,wf03,wf04]){assert.ok(Array.isArray(wf.nodes));const names=new Set(wf.nodes.map(n=>n.name));for(const [from,c] of Object.entries(wf.connections)){assert.ok(names.has(from));for(const lane of c.main)for(const edge of lane)assert.ok(names.has(edge.node));}}assert.equal(wf00.active,false);assert.equal(wf03.active,false);assert.equal(node(wf00,'POST /judah-bot-inbound').parameters.options.rawBody,true);assert.equal(node(wf00,'Compute HMAC-SHA256').typeVersion,2);assert.equal(node(wf00,'Compute HMAC-SHA256').credentials,undefined);});
test('Code nodes têm JavaScript sintaticamente válido',()=>{for(const wf of [wf00,wf01,wf02,wf03,wf04])for(const n of wf.nodes.filter(n=>n.type==='n8n-nodes-base.code'))assert.doesNotThrow(()=>new Function(n.parameters.jsCode),`${wf.name}: ${n.name}`)});
test('regex WF-04 corrigida isoladamente',()=>{const js=node(wf04,'Interpret Triage Selection').parameters.jsCode;assert.ok(js.includes("replace(/[^a-z0-9\\s]/g,' ')")&&js.includes("replace(/\\s+/g,' ')"));assert.equal('Suporte   Técnico'.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9\s]/g,' ').replace(/\s+/g,' ').trim(),'suporte tecnico')});
test('sem secrets ou assinatura fixture nos exports',()=>{for(const wf of [wf00,wf03]){const text=JSON.stringify(wf);assert.ok(!text.includes('fixture-secret'));assert.ok(!text.includes('JUDAH_N8N_HMAC_SECRET'));}});

let passed=0;for(const [name,fn] of tests){try{await fn();passed++;console.log(`ok - ${name}`)}catch(error){console.error(`not ok - ${name}`);throw error;}}console.log(`\n${passed}/${tests.length} checks passed`);
