from pathlib import Path

views = Path('ecom/views.py')
t = views.read_text(encoding='utf-8')
t = t.replace("data.get('commandes_objets')", "data.get('commandes_objets')")
views.write_text(t, encoding='utf-8')

# Use helper keys exactly as in dashboard.py
keys_src = Path('ecom/dashboard.py').read_text(encoding='utf-8')
# extract exact key strings from helper
import re
m_montant = re.search(r"'montant_par_mois'", keys_src).group(0)
m_max = re.search(r"'max_montant_mois'", keys_src).group(0)
m_obj = re.search(r"'commandes_objets'", keys_src).group(0)

t = Path('ecom/views.py').read_text(encoding='utf-8')
t = re.sub(r"data\.get\('commandes_[^']+'\)", f"data.get({m_obj})", t)
Path('ecom/views.py').write_text(t, encoding='utf-8')

html = Path('ecom/templates/e_autopiece/dashboard.html').read_text(encoding='utf-8')
html = re.sub(r'dash\.montant_par_mois', f'dash.{m_montant.strip(chr(39))}', html)
html = re.sub(r'dash\.max_montant_mois', f'dash.{m_max.strip(chr(39))}', html)

urls = Path('ecom/urls.py').read_text(encoding='utf-8')
inv = re.search(r"name='(ecom_[^']*invoice[^']*)'", urls).group(1)
wish = re.search(r"name='(ecom_[^']*wishlist[^']*)'", urls).group(1)
html = re.sub(r"url 'ecom_[^']*invoice[^']*'", f"url '{inv}'", html)
html = re.sub(r"url 'ecom_[^']*wishlist[^']*'", f"url '{wish}'", html)
Path('ecom/templates/e_autopiece/dashboard.html').write_text(html, encoding='utf-8')
print('obj', m_obj, 'montant', m_montant, 'invoice', inv, 'wishlist', wish)
