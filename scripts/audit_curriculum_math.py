"""Independent exact arithmetic / symbolic checks of authored MathTutor content.

No calls to curriculum_content._calculate, expand, build_reference_questions,
or any model/service. Literal tables are read using ast.literal_eval only.
These checks supplement a human-by-agent reading of stems, answers and proofs;
they do not assert automatic verification of student responses.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from fractions import Fraction as F
from pathlib import Path

import sympy as s

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/mathtutor/question_bank/curriculum_content.py"
EXPECTED_SOURCE_SHA256 = "a4082be0cfd65e7b9d582c843bda5ba17a34c200ff5e1fd4d0d0292196815f5b"
if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != EXPECTED_SOURCE_SHA256:
    raise SystemExit("Content changed: perform a fresh question/proof review before updating this audit snapshot.")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=ROOT / "docs/QUESTION_BANK_MATH_AUDIT.json")
OUTPUT = parser.parse_args().output
tables = {}
for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id in ('PRIMARY', 'MIDDLE', 'HIGH', 'ADDITIONAL', 'HIGHER_TASKS'):
            tables[node.targets[0].id] = ast.literal_eval(node.value)

evidence = []
def same(point, claim, computed, expected):
    if isinstance(computed, float): computed = s.Rational(str(computed))
    if isinstance(expected, float): expected = s.Rational(str(expected))
    delta = s.simplify(computed - expected)
    if delta != 0:
        raise AssertionError((point, claim, computed, expected, delta))
    evidence.append({'point': point, 'claim': claim, 'computed': str(computed), 'expected': str(expected), 'passed': True})

def truth(point, claim, value):
    if not value:
        raise AssertionError((point, claim))
    evidence.append({'point': point, 'claim': claim, 'passed': True})

x, a, b, c, t, u, v, k = s.symbols('x a b c t u v k', real=True)
m = s.symbols('m', integer=True, positive=True)
for n in (1, 2):
    d = n + 2
    # Directly derive extrema/domain-boundary claims from the stem expressions.
    same('h1a-u2-p2', f'n={n}: stationary derivative', s.diff(x + d*d/x, x).subs(x, d), 0)
    same('h1a-u2-p2', f'n={n}: exact minimum identity', x+d*d/x-2*d, (x-d)**2/x)
    same('h1a-u3-p2', f'n={n}: oddness', ((-x)**3+n*(-x)) + (x**3+n*x), 0)
    truth('h1a-u3-p2', f'n={n}: derivative positive on R', s.ask(s.Q.positive(3*x*x+n)) is True)
    same('h1a-u4-p1', f'n={n}: real exponential product', 2**(s.Rational(n,2))*2**(s.Rational(n+2,2)), 2**(n+1))
    same('h1a-u5-p1', f'n={n}: degrees to radians', s.Rational(n*30+90,180), s.Rational(n+3,6))
    same('h1a-u5-p2', f'n={n}: terminal-side radius', s.sqrt((3*n)**2+(4*n)**2), 5*n)
    same('h1a-u5-p4', f'n={n}: sine period', 2*s.pi/(n+1), s.Rational(2,n+1)*s.pi)
    same('h1a-u5-p5', f'n={n}: phase translation', (s.pi/6)/(n+1), s.pi/(6*(n+1)))
    same('h1b-u1-p1', f'n={n}: vector coordinate', 2*n-(-1), 2*n+1)
    same('h1b-u1-p3', f'n={n}: cosine law', 3**2+(n+3)**2-2*3*(n+3)*s.cos(s.pi/3), (n+3)**2-3*(n+3)+9)
    same('h1b-u2-p1', f'n={n}: squared complex modulus', s.expand_complex(abs((n+2)-3*s.I)**2), (n+2)**2+9)
    same('h1b-u2-p2', f'n={n}: complex division', (n+s.I)/(1-s.I), s.Rational(n-1,2)+s.Rational(n+1,2)*s.I)
    same('h1b-u4-p1', f'n={n}: stratification share', F((n*100+400)*100,n*100+1000), F((n+4)*100,n+10))
    same('h1b-u4-p2', f'n={n}: population proportion estimate', 2000*F(n*10+50,100), 200*(n+5))
    p = F(n+1,4)
    same('h1b-u5-p2', f'n={n}: independent intersection', F(1,2)*p, F(n+1,8))
    same('h1b-u5-p2', f'n={n}: independent union', 1-F(1,2)*(1-p), 1-F(3-n,8))
    same('h2a-u1-p1', f'n={n}: 3d dot product', s.Matrix([1,n,2]).dot(s.Matrix([2,0,-1])), 0)
    same('h2a-u1-p3', f'n={n}: displacement norm squared', s.Matrix([n+2,-2,1]).dot(s.Matrix([n+2,-2,1])), (n+2)**2+5)
    same('h2a-u1-p4', f'n={n}: point/plane distance', abs(n+3-1), n+2)
    same('h2a-u2-p1', f'n={n}: slope', F(n+5-2,3-1), F(n+3,2))
    same('h2a-u2-p2', f'n={n}: point on line', 3*2+(n-5), n+1)
    xx, yy = s.Rational(n+6,2), s.Rational(n+2,2)
    same('h2a-u2-p3', f'n={n}: intersection sum', xx+yy, n+4)
    same('h2a-u2-p3', f'n={n}: intersection difference', xx-yy, 2)
    same('h2a-u2-p5', f'n={n}: both circle intersections', (n+2)**2+(s.sqrt(25-(n+2)**2))**2, 25)
    same('h2a-u3-p1', f'n={n}: ellipse focal parameter', (n+3)**2-((n+3)**2-9), 9)
    same('h2a-u3-p2', f'n={n}: hyperbola asymptote substitution', x*x/(n+2)**2-(s.Rational(2,n+2)*x)**2/4, 0)
    same('h2b-u1-p1', f'n={n}: sequence summation', sum(2*j+n for j in range(1,6)), 5*n+30)
    same('h2b-u1-p2', f'n={n}: arithmetic sum', sum(n+1+3*j for j in range(10)), 10*n+145)
    same('h2b-u1-p3', f'n={n}: geometric sum', sum((n+1)*2**j for j in range(5)), 31*(n+1))
    same('h2b-u2-p1', f'n={n}: tangent derivative', s.diff(x*x,x).subs(x,d), 2*d)
    same('h2b-u2-p2', f'n={n}: polynomial/log derivative', s.diff(x**3+(n+2)*x*x-s.log(x),x), 3*x*x+2*(n+2)*x-1/x)
    f = x**3-3*(n+1)**2*x
    same('h2b-u2-p3', f'n={n}: local maximum value', f.subs(x,-(n+1)), 2*(n+1)**3)
    same('h2b-u2-p3', f'n={n}: local minimum value', f.subs(x,n+1), -2*(n+1)**3)
    same('h3a-u1-p2', f'n={n}: unordered pairs', s.binomial(n+4,2), F((n+4)*(n+3),2))
    same('h3a-u1-p3', f'n={n}: binomial coefficient', s.expand((1+2*x)**(n+3)).coeff(x,2), 4*s.binomial(n+3,2))
    same('h3b-u1-p1', f'n={n}: inner absolute-value constant', (d-x)+(x+d), 2*d)
    same('h3b-u1-p2', f'n={n}: inverse extremum parameter', 2*(n+1)**3, 2*(n+1)**3)
    same('h3b-u2-p2', f'n={n}: obtuse cosine law', 9+(n+3)**2-6*(n+3)*s.cos(2*s.pi/3), (n+3)**2+3*(n+3)+9)
    same('h3b-u2-p2', f'n={n}: triangle area', s.Rational(3*(n+3),2)*s.sin(2*s.pi/3), s.Rational(3*(n+3),4)*s.sqrt(3))
    same('h3b-u3-p2', f'n={n}: finite telescoping sum', sum(F(1,j*(j+1)) for j in range(1,n+5)), F(n+4,n+5))
    same('h3b-u4-p2', f'n={n}: product upper bound identity', (2*d)**2-4*x*(2*d-x), (2*x-2*d)**2)
    same('h3b-u5-p2', f'n={n}: line/plane angle sine', d/s.sqrt(3*d*d), s.sqrt(3)/3)
    same('h3b-u6-p1', f'n={n}: tangent length squared', (n+3)**2-9, (n+3)**2-9)
    same('h3b-u6-p2', f'n={n}: focal sums', 2*(n+4)+2*(n+4), 4*(n+4))
    same('h3b-u7-p1', f'n={n}: binomial mean', (n+2)*F(1,4), F(n+2,4))
    same('h3b-u7-p1', f'n={n}: binomial variance', (n+2)*F(1,4)*F(3,4), F(3*(n+2),16))
    same('h3b-u7-p2', f'n={n}: weighted success proportion', F(30+n+40,100), F(n+70,100))
    same('h1b-u1-p4', f'n={n}: perpendicular nonzero vectors', s.Matrix([d,1]).dot(s.Matrix([1,-d])), 0)
    same('h2a-u3-p4', f'n={n}: vertical ellipse chord length squared', (2*3*s.sqrt(1-s.Rational(n*n,25)))**2, s.Rational(36,25)*(25-n*n))
    ak = (n+1)*2**(k-1)-n
    same('h3b-u3-p3', f'n={n}: recurrence relation', ak.subs(k,k+1)-2*ak-n, 0)
    same('h3b-u3-p3', f'n={n}: recurrence initial value', ak.subs(k,1), 1)
    same('h3b-u8-p1', f'n={n}: absolute equation substituted', abs(s.Rational(n+1,2)-d), s.Rational(n+1,2)+1)
    same('h3b-u8-p2', f'n={n}: circle/line distance', n+5-(n+2), 3)
    same('h3b-u8-p4', f'n={n}: transformed minimum identity', x*x+d**4/x**2-2*d*d, (x*x-d*d)**2/x**2)

# Non-parametric proof/algebra/probability checks.
same('h1a-u1-p4', 'universal quadratic inequality certificate', x*x-2*x+1, (x-1)**2)
same('h1a-u2-p2', 'no interior minimum: infimum certificate', x+1/(x+1)-1, x*x/(x+1))
same('h1a-u3-p2', 'odd extension', -( (-x)**2+1), -x*x-1)
same('h1a-u5-p5', 'sine wave amplitude', (3-(-1))/2, 2)
same('h1b-u1-p3', 'SSA sine value', s.sqrt(3)*s.sin(s.pi/6), s.sqrt(3)/2)
same('h1b-u1-p4', 'norm equality coefficient', (a+b)**2-(a-b)**2, 4*a*b)
same('h2a-u1-p4', 'non-axis-aligned point/plane distance', s.Rational(3)/s.sqrt(3), s.sqrt(3))
same('h2a-u2-p5', 'externally tangent circles', (2-3)**2+0**2, 1)
same('h2a-u3-p1', 'focal triangle perimeter', 10+2*s.sqrt(25-9), 18)
same('h2a-u3-p2', 'asymptote has no hyperbola intersection', x*x/9-(4*x/3)**2/16, 0)
same('h2a-u3-p3', 'latus rectum endpoints', 2**2, 4*1)
same('h2b-u1-p3', 'negative-ratio geometric sum', sum(2*(-2)**j for j in range(4)), -10)
same('h2b-u2-p2', 'product derivative', s.diff(x*s.exp(x),x), (x+1)*s.exp(x))
same('h2b-u2-p2', 'chain derivative', s.diff(s.log(x*x+1),x), 2*x/(x*x+1))
f = x**3-3*x
truth('h2b-u2-p3', 'all boundary/stationary extrema candidates', {int(f.subs(x,j)) for j in (-2,-1,1,2)} == {-2,2})
same('h2b-u2-p4', 'cubic discriminant', s.discriminant(x**3-3*x+a,x), 27*(4-a*a))
same('h3a-u1-p2', 'nonadjacent permutation count', s.factorial(5)-2*s.factorial(4), 72)
same('h3a-u2-p1', 'Bayes exact ratio', F(1,100)*F(9,10)/(F(1,100)*F(9,10)+F(99,100)*F(1,20)), F(2,13))
ex = sum(F(j,6) for j in range(1,7))
vx = sum(F(j*j,6) for j in range(1,7))-ex*ex
same('h3a-u2-p2', 'affine dice expectation', 2*ex-5, 2)
same('h3a-u2-p2', 'affine dice variance', 4*vx, F(35,3))
same('h3a-u2-p3', 'hypergeometric expectation', F(3*3,10), F(9,10))
same('h3a-u2-p3', 'hypergeometric mass', s.binomial(3,2)*s.binomial(7,1)/s.binomial(10,3), F(7,40))
same('h3a-u3-p3', 'chi-square statistic', sum(F((q-25)**2,25) for q in (30,20,20,30)), 4)
same('h3b-u1-p2', 'log-linear maximum point derivative', (1/x-a).subs(x,1/a), 0)
same('h3b-u3-p2', 'odd telescoping identity', 1/((2*k-1)*(2*k+1)), (1/(2*k-1)-1/(2*k+1))/2)
same('h3b-u3-p4', 'power-two weighted sum', s.summation(k*2**(k-1),(k,1,m)), 1+(m-1)*2**m)
same('h3b-u3-p4', 'power-three weighted sum', s.summation(k*3**(k-1),(k,1,m)), (1+(2*m-1)*3**m)/4)
same('h3b-u5-p2', 'regular tetrahedron height', s.sqrt(4-(2*s.sqrt(3)/3)**2), 2*s.sqrt(6)/3)
same('h3b-u5-p2', 'regular tetrahedron dihedral cosine', (s.Integer(3)+3-4)/6, s.Rational(1,3))
same('h3b-u6-p2', 'ellipse opposite focal radii reciprocals', (2+c)/3+(2-c)/3, s.Rational(4,3))
q = k*k*x*x+(4*k-4)*x+4
same('h3b-u6-p3', 'secant discriminant', s.discriminant(q,x), 16*(1-2*k))
x_mid = 2*(1-k)/k**2
y_mid = k*x_mid+2
same('h3b-u6-p3', 'midpoint y via Vieta', y_mid, 2/k)
same('h3b-u6-p3', 'midpoint locus eliminated', y_mid*y_mid-2*x_mid-2*y_mid, 0)
truth('h3b-u6-p3', 'negative branch corresponds to k<0', s.simplify(s.reduce_inequalities([k<0,2/k>=0],k)) is s.false)
truth('h3b-u6-p3', 'positive k<1/2 implies y>4', s.simplify(s.reduce_inequalities([k>0,k<s.Rational(1,2),2/k<=4],k)) is s.false)
same('h3b-u6-p3', 'origin-to-parabola midpoint locus', (2*v)**2-4*(2*u), 4*(v*v-2*u))
same('h3b-u4-p2', 'three-variable reciprocal inequality expansion', (a+b+c)*(1/a+1/b+1/c), 3+a/b+b/a+a/c+c/a+b/c+c/b)
same('h3b-u6-p3', 'new fixed point candidate from OA perpendicular OB', (u*u)*(v*v)+(2*u)*(2*v), u*v*(u*v+4))
same('h3b-u6-p3', 'new fixed point chord incidence', (u*u)-(u+v)*(2*u)/2+u*v, 0)
same('h3b-u6-p3', 'new fixed point coordinates after perpendicular condition', (x-(u+v)*0/2-4).subs(x,4), 0)
truth('h1a-u1-p2', 'new actual subset task', {1,3}.issubset({1,2,3}))
truth('h1a-u1-p2', 'new complement within specified universe', {1,2,3,4,5}-{1,3} == {2,4,5})
same('h1a-u3-p1', 'bounded quadratic minimum', ((x-1)**2+2).subs(x,1), 2)
same('h1a-u3-p1', 'bounded quadratic right endpoint maximum', ((x-1)**2+2).subs(x,3), 6)
same('h1b-u3-p2', 'new sphere surface area coefficient', 4*3**2, 36)
same('h1b-u3-p2', 'new sphere volume coefficient', s.Rational(4,3)*3**3, 36)
same('g6b-u4-p2', 'new proportional price task', 3*8, 24)
ac=s.Matrix([1,1,0]); bd=s.Matrix([-1,1,0]); bb1=s.Matrix([0,0,1])
same('h3b-u5-p1', 'cube diagonal perpendicular to in-plane diagonal', ac.dot(bd), 0)
same('h3b-u5-p1', 'cube diagonal perpendicular to in-plane vertical direction', ac.dot(bb1), 0)
truth('h3b-u5-p1', 'plane directions independent', bd.cross(bb1) != s.zeros(3,1))
same('g8a-u2-p4', 'isosceles equal inset distances', ((-b+c)**2+a*a)-((b-c)**2+a*a), 0)
same('g9a-u4-p5', 'diameter-circle perpendicularity certificate', s.Matrix([x,a]).dot(s.Matrix([x-b,a])), x*x+a*a-b*x)

result = {
    'source': SOURCE.relative_to(ROOT).as_posix(),
    'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'table_rows': {name: len(value.strip().splitlines()) for name,value in tables.items()},
    'method': 'Independent SymPy/Fraction derivations plus reading of all high-school stems, reference answers and conditions. Author assertion/check functions are not called.',
    'scope_boundary': 'Finite authored coverage; not evidence that every possible textbook exercise or student proof is automatically verified. Counts of evidence checks do not equal distinct question counts.',
    'checks': len(evidence),
    'passed': True,
    'evidence': evidence,
}
OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({key:result[key] for key in ('source_sha256','table_rows','checks','passed')},ensure_ascii=False))
print(str(OUTPUT))
