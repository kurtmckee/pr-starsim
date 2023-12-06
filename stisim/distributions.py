""" 
stisim distributions

Example usage

>>> dist = stisim.normal(1,1) # Make a distribution
>>> dist()  # Draw a sample
>>> dist(10) # Draw several samples
>>> dist.sample(10) # Same as above
>>> stisim.State('foo', float, fill_value=dist)  # Use distribution as the fill value for a state
>>> disease.pars['immunity'] = dist  # Store the distribution as a parameter
>>> disease.pars['immunity'].sample(5)  # Draw some samples from the parameter
>>> stisim.poisson(rate=1).sample(10)  # Sample from a temporary distribution
"""

import numpy as np
from stisim.utils import INT_NAN
from stisim.random import MultiRNG
from stisim import options, int_

__all__ = ['ScipyDistribution'] #'rate', 

from scipy.stats._discrete_distns import bernoulli_gen
#from scipy.stats import bernoulli


class ScipyDistribution():
    def __init__(self, gen, rng=None):
        class starsim_gen(type(gen.dist)):
            def initialize(self, sim):
                self.sim = sim
                return

            def rvs(self, *args, **kwargs):
                """
                Return a specified number of samples from the distribution
                """

                size = kwargs['size']
                # Work out how many samples to draw. If sampling by UID, this depends on the slots assigned to agents.
                if np.isscalar(size):
                    if not isinstance(size, (int, np.int64, int_)):
                        raise Exception('Input "size" must be an integer')
                    if size < 0:
                        raise Exception('Input "size" cannot be negative')
                    elif size == 0:
                        return np.array([], dtype=int) # int dtype allows use as index, e.g. when filtering
                    else:
                        n_samples = size
                elif len(size) == 0:
                    return np.array([], dtype=int)
                elif size.dtype == bool:
                    n_samples = len(size) if options.multirng else size.sum()
                elif size.dtype in [int, np.int64, int_]:
                    if not options.multirng:
                        n_samples = len(size)
                    else:
                        v = size.__array__() # TODO - check if this works without calling __array__()?
                        try:
                            max_slot = self.random_state.slots[v].__array__().max()
                        except AttributeError as e:
                            if not isinstance(self.random_state, MultiRNG):
                                raise Exception('With options.multirng and passing agent UIDs to a distribution, the random_state of the distribution must be a MultiRNG.')
                            else:
                                if not self.random_state.initialized:
                                    raise Exception('The MultiRNG instance must be initialized before use.')
                            raise e

                        if max_slot == INT_NAN:
                            raise Exception('Attempted to sample from an INT_NAN slot')
                        n_samples = max_slot + 1
                else:
                    raise Exception("Unrecognized input type")

                # Now handle distribution arguments
                for pname in [p.name for p in self._param_info()]:
                    if pname in kwargs and callable(kwargs[pname]):
                        kwargs[pname] = kwargs[pname](self.sim, size)

                    if (pname in kwargs) and (not np.isscalar(kwargs[pname])) and (len(kwargs[pname]) != n_samples):
                        # Fill in the blank. The number of UIDs provided is
                        # hopefully consistent with the length of pars
                        # provided, but we need to expand out the pars to be
                        # n_samples in length.
                        if len(kwargs[pname]) not in [len(size), sum(size)]: # Could handle uid and bool separately? len(size) for uid and sum(size) for bool
                            raise Exception('When providing an array of parameters, the length of the parameters must match the number of agents for the selected size (uids).')
                        vals_all = np.full(n_samples, fill_value=1) # self.fill_value
                        vals_all[size] = kwargs[pname]
                        kwargs[pname] = vals_all

                kwargs['size'] = n_samples
                vals = super().rvs(*args, **kwargs) # Add random_state here?
                if isinstance(self, bernoulli_gen):
                    vals = vals.astype(bool)

                # _select:
                if not options.multirng:
                    return vals

                if np.isscalar(size):
                    return vals
                elif size.dtype == bool:
                    return vals[size]
                else:
                    slots = self.random_state.slots[size].__array__()
                    return vals[slots]

        self.rng = self.set_rng(rng, gen)
        self.gen = starsim_gen(name=gen.dist.name, seed=self.rng)(**gen.kwds)
        return
    
    @staticmethod
    def set_rng(rng, gen):
        # Handle random generators
        ret = gen.random_state # Default
        if options.multirng and rng and (gen.random_state == np.random.mtrand._rand):
            # MultiRNG, rng not none, and the current "random_state" is the
            # numpy global singleton... so let's override
            if isinstance(rng, str):
                ret = MultiRNG(rng) # Crate a new generator with the user-provided string
            elif isinstance(rng, np.random.Generator):
                ret = rng
            else:
                raise Exception(f'The rng must be a string or a np.random.Generator instead of {type(rng)}')
        return ret

    def initialize(self, sim):
        self.gen.dist.initialize(sim)
        if isinstance(self.rng, MultiRNG):
            self.rng.initialize(sim.rng_container, sim.people.slot)
        return

    def __getattr__(self, attr):
        # Returns wrapped generator.(attr) if not a property
        try:
            return self.__getattribute__(attr)
        except Exception:
            try:
                return getattr(self.gen, attr) # .dist?
            except Exception as e:
                if '__getstate__' in str(e):
                    # Must be from pickle, return a callable function that returns None
                    return lambda: None
                elif '__await__' in str(e):
                    # Must be from async programming?
                    return None
                elif '__deepcopy__' in str(e):
                    # from sc.dcp
                    return None
                errormsg = f'"{attr}" is not a member of this class or the underlying scipy stats class'
                raise Exception(errormsg)

    def filter(self, size, **kwargs):
        return size[self.gen.rvs(size, **kwargs)]

'''
class rate(ScipyDistribution):
    """
    Exponentially distributed, accounts for dt.
    Assumes the rate is constant over each dt interval.
    """
    def __init__(self, p, rng=None):
        dist = bernoulli(p=p)
        super().__init__(dist, rng)
        self.rate = rate
        self.dt = None
        return

    def initialize(self, sim, rng):
        self.dt = sim.dt
        self.rng = self.set_rng(rng, self.gen)
        super().initialize(sim)
        return

    def sample(self, size=None):
        n_samples, pars = super().sample(size, rate=self.rate)
        prob = 1 - np.exp(-pars['rate'] * self.dt)
        vals = self.rng.random(size=n_samples)
        vals = self._select(vals, size)
        return vals < prob
'''