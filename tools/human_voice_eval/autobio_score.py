import json, statistics as st, math
# (A_consistency, A_naturalness, B_consistency, B_naturalness), scored blind (arm labels unseen), 1-5 each
S = {1:(4,2,5,4),2:(5,4,4,4),3:(5,4,5,3),4:(4,4,3,3),5:(2,4,5,2),6:(2,3,1,3),7:(3,4,2,3),8:(5,4,4,5),9:(2,3,1,2),10:(5,5,5,5),
     11:(5,5,4,3),12:(4,1,5,4),13:(5,4,5,5),14:(4,2,4,4),15:(4,2,5,5),16:(5,4,4,4),17:(3,3,4,3),18:(5,5,1,1),19:(4,3,4,3),20:(5,5,2,2),
     21:(4,2,5,5),22:(4,3,4,4),23:(5,3,5,5),24:(3,3,3,3),25:(1,4,4,4),26:(3,3,3,3),27:(2,3,2,3),28:(5,4,5,5),29:(1,2,1,2),30:(5,5,5,5),
     31:(5,4,5,5),32:(5,4,5,4),33:(4,2,5,5),34:(4,1,4,3),35:(5,4,4,3),36:(5,4,4,4),37:(3,3,4,3),38:(4,4,1,1),39:(4,4,3,2),40:(4,4,5,5)}
key = json.load(open('autobio_key.json'))
tot = {'on':{'c':[],'n':[]}, 'off':{'c':[],'n':[]}}
wins = {'on':0,'off':0,'tie':0}
for n,(ac,an,bc,bn) in S.items():
    k = key[str(n)]
    for side,(c,nn) in (('A',(ac,an)),('B',(bc,bn))):
        tot[k[side]]['c'].append(c); tot[k[side]]['n'].append(nn)
    sa, sb = ac+an, bc+bn
    wins['tie' if sa==sb else (k['A'] if sa>sb else k['B'])] += 1
for arm in ('on','off'):
    print(arm, 'consistency mean', round(st.mean(tot[arm]['c']),2), 'naturalness mean', round(st.mean(tot[arm]['n']),2))
print('wins (consistency+naturalness):', wins)
w, l = wins['on'], wins['off']
n = w + l
p = sum(math.comb(n,i) for i in range(max(w,l), n+1)) * 2 / 2**n if n else 1
print('sign test two-sided p =', round(min(1,p),3))
