import numpy as np

def rule_of_mixtures(Vf, prop_f, prop_m):
    """
    Standard Rule of Mixtures (Voigt model) for longitudinal properties.
    """
    Vm = 1.0 - Vf
    return Vf * prop_f + Vm * prop_m

def inverse_rule_of_mixtures(Vf, prop_f, prop_m):
    """
    Inverse Rule of Mixtures (Reuss model) for transverse/shear properties.
    """
    if prop_f == 0.0 or prop_m == 0.0:
        return 0.0
    Vm = 1.0 - Vf
    return 1.0 / (Vf / prop_f + Vm / prop_m)

def chamis_transverse_modulus(Vf, Ef, Em):
    """
    Chamis semi-empirical formula for Transverse Modulus (E22, E33).
    Often more accurate than Reuss model for polymer matrix composites.
    """
    if Ef == 0.0 or Em == 0.0:
        return 0.0
    return Em / (1.0 - np.sqrt(Vf) * (1.0 - Em / Ef))

def chamis_shear_modulus(Vf, Gf, Gm):
    """
    Chamis semi-empirical formula for In-Plane Shear Modulus (G12).
    """
    if Gf == 0.0 or Gm == 0.0:
        return 0.0
    return Gm / (1.0 - np.sqrt(Vf) * (1.0 - Gm / Gf))

def calculate_lamina_properties(fiber, resin, vf):
    """
    Calculates the 3D orthotropic properties of a unidirectional continuous 
    fiber lamina given the base fiber properties, resin properties, and 
    Fiber Volume Fraction (Vf).
    
    Args:
    Args:
        fiber (dict): {'E11_t': float, 'E11_c': float, 'E22': float, 'G12': float, 'nu12': float, 'density': float, 'cte11': float, 'cte22': float, 'Xt': float, 'Xc': float}
        resin (dict): {'E_t': float, 'E_c': float, 'nu': float, 'density': float, 'cte': float, 'Xt': float, 'Xc': float, 'S': float}
        vf (float): Fiber volume fraction (e.g. 0.6)
        
    Returns:
        dict: The homogenized orthotropic lamina properties.
    """
    # Resin isotropic conversions
    # Fallback to 'E' for backwards compatibility with older db saves
    Em_t = resin.get('E_t', resin.get('E', 4.3e9))
    Em_c = resin.get('E_c', resin.get('E', 4.3e9))
    num = resin['nu']
    Gm = Em_t / (2.0 * (1.0 + num))
    
    # Longitudinal Modulus (Rule of Mixtures)
    fiber_e11_t = fiber.get('E11_t', fiber.get('E11', 230e9))
    fiber_e11_c = fiber.get('E11_c', fiber.get('E11', 230e9))
    E11_t = rule_of_mixtures(vf, fiber_e11_t, Em_t)
    E11_c = rule_of_mixtures(vf, fiber_e11_c, Em_c)
    
    # Transverse Modulus E22 (Chamis)
    E22 = chamis_transverse_modulus(vf, fiber['E22'], Em_t)
    
    # Major Poisson's Ratio nu12 (Rule of Mixtures)
    nu12 = rule_of_mixtures(vf, fiber['nu12'], num)
    
    # In-Plane Shear Modulus G12 (Chamis)
    G12 = chamis_shear_modulus(vf, fiber['G12'], Gm)
    
    # Density (Rule of Mixtures)
    density = rule_of_mixtures(vf, fiber['density'], resin['density'])
    
    # CTE Calculations (Schapery's rules for thermal expansion)
    af11 = fiber.get('cte11', 0.0)
    af22 = fiber.get('cte22', 0.0)
    am = resin.get('cte', 0.0)
    vm = 1.0 - vf
    
    # Longitudinal CTE (alpha_11)
    # Using tension modulus as the primary scaling matrix for CTE
    cte11 = (fiber_e11_t * af11 * vf + Em_t * am * vm) / E11_t if E11_t > 0.0 else 0.0
    
    # Transverse CTE (alpha_22)
    # Using the standard Schapery form which accounts for the Poisson constraint
    # alpha_22 = alpha_f*vf*(1+nu_f) + alpha_m*vm*(1+nu_m) - nu12*alpha_11
    nu_f = fiber.get('nu12', 0.2)
    cte22 = af22 * vf * (1.0 + nu_f) + am * vm * (1.0 + num) - nu12 * cte11
    
    # Basic Strength Approximations
    # Longitudinal tension/compression strength (Rule of Mixtures)
    Xt = rule_of_mixtures(vf, fiber.get('Xt', 4900e6), resin.get('Xt', 80e6))
    Xc = rule_of_mixtures(vf, fiber.get('Xc', 4000e6), resin.get('Xc', 120e6))
    
    # Transverse/Shear strengths are heavily matrix-dominated in simple homogenization
    Yt = resin.get('Xt', 80e6)
    Yc = resin.get('Xc', 120e6)
    S12 = resin.get('S', 50e6)
    
    return {
        'E11_t': E11_t,
        'E11_c': E11_c,
        'E11': E11_t, # Backwards compatibility for existing tools
        'E22': E22,
        'G12': G12,
        'nu12': nu12,
        'density': density,
        'cte11': cte11,
        'cte22': cte22,
        'Xt': Xt,
        'Xc': Xc,
        'Yt': Yt,
        'Yc': Yc,
        'S12': S12
    }
