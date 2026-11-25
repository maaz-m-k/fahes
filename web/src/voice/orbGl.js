/* The voice circle the team lead picked: "Calm gulf teal" (Aurora swirl). The WebGL shader and the energy model are
   copied unchanged from the approved prototype (data/proto-studio/proto/public/orb.js). */
/* eslint-disable */
export const TEAL = { id: 'teal', style: 3, seed: 2.6, c: ['#0A4D4A', '#0F8B8D', '#2BB673', '#A7F3D0'], w: [1, 1, .8, .55], en: 'Calm gulf teal' };
const VS = 'attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
const FS = `precision highp float;
uniform vec2 uRes;uniform float uT,uPh,uUser,uSelf,uSeed,uStyle;
uniform vec3 uC0,uC1,uC2,uC3;uniform vec4 uW;
float hash(vec3 p){p=fract(p*0.3183099+.1);p*=17.0;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float noise(vec3 x){vec3 i=floor(x);vec3 f=fract(x);f=f*f*(3.0-2.0*f);
 return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
  mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p){float v=0.,a=.5;for(int i=0;i<4;i++){v+=a*noise(p);p=p*2.02+vec3(1.7,9.2,3.1);a*=.5;}return v;}
float h2(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
void main(){
 vec2 uv=(gl_FragCoord.xy-.5*uRes)/min(uRes.x,uRes.y);
 float e=clamp(uUser+uSelf,0.,1.2);
 float r=length(uv);float a=atan(uv.y,uv.x);
 float breath=.014*sin(uT*1.25)+.006*sin(uT*.71+uSeed);
 float base=.31+breath+.055*uUser+.04*uSelf;
 vec2 dir=uv/max(r,1e-4);
 float n=fbm(vec3(dir*1.4+uSeed,uPh*.35));
 float amp=.04+.13*uUser+.05*uSelf;
 float rad=base+(n-.5)*amp*2.;
 float sdf=r-rad;
 if(uStyle>1.5&&uStyle<2.5){
  float k=.12;sdf=1e3;
  for(int i=0;i<3;i++){float fi=float(i);
   vec2 c=vec2(cos(uPh*.5+fi*2.094+uSeed),sin(uPh*.43+fi*2.094))*(.065+.09*uUser+.03*uSelf);
   float rr=base*.74+(noise(vec3(fi*3.,uPh*.4,uSeed))-.5)*.07;
   float d=length(uv-c)-rr;
   float h=clamp(.5+.5*(sdf-d)/k,0.,1.);sdf=mix(sdf,d,h)-k*h*(1.-h);}
  sdf+=(n-.5)*amp;
 } else if(uStyle>2.5){ sdf-=.018*sin(a*3.+uPh*.8)*(1.+2.*uUser); }
 float soft=.02+.03*e;
 float mask=1.-smoothstep(-soft,soft*1.5,sdf);
 vec2 q=uv*1.7;
 if(uStyle>2.5){float ang=r*5.5-uPh*.3;float cs=cos(ang),sn=sin(ang);q=mat2(cs,-sn,sn,cs)*uv*1.9;}
 vec2 w=vec2(fbm(vec3(q,uPh*.2+uSeed)),fbm(vec3(q+5.2,uPh*.2-uSeed)));
 float f1=fbm(vec3(q+w*2.,uPh*.25));
 float f2=fbm(vec3(q*1.3-w*1.5+3.,uPh*.18));
 vec3 col=mix(uC0,uC1,smoothstep(.3,.6,f1));
 col=mix(col,uC2,smoothstep(.4,.64,f2)*uW.z);
 col=mix(col,uC3,smoothstep(.5,.7,f1*.5+f2*.6)*uW.w);
 col*=1.12;vec2 lp=vec2(cos(uPh*.21+uSeed),sin(uPh*.17))*.09+vec2(-.05,.08);col+=mix(uC2,uC3,.5)*.32*exp(-length(uv-lp)*9.)*uW.w;col+=.12*(1.-smoothstep(0.,rad,r))*(.45+e);
 float inner=.66+.34*smoothstep(.3,.6,f1);
 if(uStyle>.5&&uStyle<1.5){inner*=mix(.1,1.,smoothstep(rad*.2,rad*.97,r));}
 float glow=exp(-max(sdf,0.)*15.)*(.2+.35*e)*(1.-mask);
 float alpha=mask*inner+glow;float edgeF=1.-smoothstep(.40,.5,r);glow*=edgeF;alpha=(mask*inner+glow)*edgeF;
 vec3 outc=col*mask*inner+mix(uC1,uC2,.45)*glow;
 float g=h2(gl_FragCoord.xy+fract(uT*7.13)*97.)-.5;
 outc+=g*.13*alpha;alpha=clamp(alpha+g*.07*mask,0.,1.);
 outc=clamp(outc,0.,1.)*1.;outc=min(outc,vec3(alpha));
 gl_FragColor=vec4(outc,alpha);
}`;
const hex3 = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
function makeOrb(canvas, cand) {
  const gl = canvas.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false });
  if (!gl) return null;
  const sh = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o);
    if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(o)); return o; };
  const pr = gl.createProgram();
  gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(pr); gl.useProgram(pr);
  const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(pr, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = {}; ['uRes', 'uT', 'uPh', 'uUser', 'uSelf', 'uSeed', 'uStyle', 'uC0', 'uC1', 'uC2', 'uC3', 'uW'].forEach(n => U[n] = gl.getUniformLocation(pr, n));
  const orb = { gl, U, canvas, cand: null };
  orb.set = c => { orb.cand = c;
    c.c.forEach((h, i) => gl.uniform3fv(U['uC' + i], hex3(h)));
    gl.uniform4fv(U.uW, c.w); gl.uniform1f(U.uSeed, c.seed); gl.uniform1f(U.uStyle, c.style); };
  orb.set(cand);
  orb.draw = (t, ph, user, self) => {
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(U.uRes, canvas.width, canvas.height);
    gl.uniform1f(U.uT, t); gl.uniform1f(U.uPh, ph); gl.uniform1f(U.uUser, user); gl.uniform1f(U.uSelf, self);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };
  return orb;
}
export { makeOrb };
