"""
Define cholera model.
Adapted from https://github.com/optimamodel/gavi-outbreaks/blob/main/stisim/gavi/cholera.py
Original version by Dom Delport 2024
"""

import numpy as np
import starsim as ss

__all__ = ['Cholera']


class Cholera(ss.Infection):
    """
    Cholera
    """
    def __init__(self, pars=None, *args, **kwargs):
        """ Initialize with parameters """
        super().__init__()
        self.default_pars(
            # Initial conditions and beta
            beta = 1.0, # Placeholder value
            init_prev = ss.bernoulli(0.005),
            
            # Natural history parameters, all specified in days
            dur_exp2inf   = ss.lognorm_ex(mean=2.772, stdev=4.737), # Calculated from Azman et al. estimates https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3677557/
            dur_asymp2rec = ss.uniform(low=1, high=10), # From WHO cholera fact sheet, asymptomatic individuals shed bacteria for 1-10 days (https://www.who.int/news-room/fact-sheets/detail/cholera)
            dur_symp2rec  = ss.lognorm_ex(mean=5, stdev=1.8), # According to Fung most modelling studies assume 5 days of symptoms (https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3926264/), but found a range of 2.9-14 days. Distribution approximately fit to these values
            dur_symp2dead = ss.lognorm_ex(mean=1, stdev=0.5), # There does not appear to be differences in timing/duration of mild vs severe disease, but death from severe disease happens rapidly https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5767916/
            p_death       = ss.bernoulli(p=0.005), # Probability of death is typically less than 1% when treated
            p_symp        = ss.bernoulli(p=0.5), # Proportion of infected which are symptomatic, mid range of ~25% and 57% estimates from Jaclson et al (https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3795095/) and Nelson et al (https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3842031/), respectively
            asymp_trans   = 0.01, # Reduction in transmission probability for asymptomatic infection, asymptomatic carriers shed 100-1000 times less bacteria than symptomatic carriers (https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3084143/ and https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3842031/). Previous models assume a 10% relative transmissibility (https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4238032/)

            # Environmental parameters
            beta_env = 0.5 / 3, # Scaling factor for transmission from environment,
            half_sat_rate = 1_000_000, # Infectious dose in water sufficient to produce infection in 50% of  exposed, from Mukandavire et al. (https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3102413/)
            shedding_rate = 10, # Rate at which infectious people shed bacteria to the environment (per day), from Mukandavire et al. (https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3102413/)
            decay_rate = 0.033, # Rate at which bacteria in the environment dies (per day), from Chao et al. and Mukandavire et al. citing https://pubmed.ncbi.nlm.nih.gov/8882180/
            p_env_transmit = ss.bernoulli(p=0), # Probability of environmental transmission - filled out later
        )
        self.update_pars(pars, **kwargs)

        # Boolean states
        self.add_states(
            # Susceptible & infected are added automatically, here we add the rest
            ss.BoolArr('exposed'),
            ss.BoolArr('symptomatic'),
            ss.BoolArr('recovered'),
    
            # Timepoint states
            ss.FloatArr('ti_exposed'),
            ss.FloatArr('ti_symptomatic'),
            ss.FloatArr('ti_recovered'),
            ss.FloatArr('ti_dead'),
        )
        return

    @property
    def infectious(self):
        return self.infected | self.exposed

    @property
    def asymptomatic(self):
        return self.infected & ~self.symptomatic

    def init_results(self):
        """
        Initialize results
        """
        super().init_results()
        npts = self.sim.npts
        self.results += [
            ss.Result(self.name, 'new_deaths', npts, dtype=int),
            ss.Result(self.name, 'cum_deaths', npts, dtype=int),
            ss.Result(self.name, 'env_prev', npts, dtype=float),
            ss.Result(self.name, 'env_conc', npts, dtype=float),
        ]
        return

    def update_pre(self):
        """
        Adapted from https://github.com/optimamodel/gavi-outbreaks/blob/main/stisim/gavi/cholera.py
        Original version by Dom Delport
        """
        # Progress exposed -> infected
        ti = self.sim.ti
        infected = (self.exposed & (self.ti_infected <= ti)).uids
        self.infected[infected] = True

        # Progress infected -> symptomatic
        symptomatic = (self.infected & (self.ti_symptomatic <= ti)).uids
        self.symptomatic[symptomatic] = True

        # Progress symptomatic -> recovered
        recovered = (self.infectious & (self.ti_recovered <= ti)).uids
        self.exposed[recovered] = False
        self.infected[recovered] = False
        self.symptomatic[recovered] = False
        self.recovered[recovered] = True

        # Trigger deaths
        deaths = (self.ti_dead <= ti).uids
        if len(deaths):
            self.sim.people.request_death(deaths)

        # Update today's environmental prevalence
        self.calc_environmental_prev()

        return

    def calc_environmental_prev(self):
        """
        Calculate environmental prevalence
        """
        p = self.pars
        r = self.results
        ti = self.sim.ti

        n_symptomatic = self.symptomatic.sum()
        n_asymptomatic = self.asymptomatic.sum()
        old_prev = self.results.env_prev[ti-1]

        new_bacteria = p.shedding_rate * (n_symptomatic + p.asymp_trans * n_asymptomatic)
        old_bacteria = old_prev * (1 - p.decay_rate)

        r.env_prev[ti] = new_bacteria + old_bacteria
        r.env_conc[ti] = r.env_prev[ti] / (r.env_prev[ti] + p.half_sat_rate)
        return

    def set_prognoses(self, uids, source_uids=None):
        """ Set prognoses for those who get infected """
        super().set_prognoses(uids, source_uids)
        ti = self.sim.ti
        dt = self.sim.dt

        self.susceptible[uids] = False
        self.exposed[uids] = True
        self.ti_exposed[uids] = ti

        p = self.pars

        # Determine when exposed become infected
        self.ti_infected[uids] = ti + p.dur_exp2inf.rvs(uids) / dt

        # Determine who becomes symptomatic and when
        symp_uids = p.p_symp.filter(uids)
        self.ti_symptomatic[symp_uids] = self.ti_infected[symp_uids]

        # Determine who dies and when
        dead_uids = p.p_death.filter(symp_uids)
        self.ti_dead[dead_uids] = self.ti_symptomatic[dead_uids] + p.dur_symp2dead.rvs(dead_uids) / dt
        symp_rev_uids = np.setdiff1d(symp_uids, dead_uids)
        asymp_uids = np.setdiff1d(uids, symp_uids)

        # Determine when agents recover
        self.ti_recovered[symp_rev_uids] = self.ti_exposed[symp_rev_uids] + p.dur_symp2rec.rvs(symp_rev_uids) / dt
        self.ti_recovered[asymp_uids] = self.ti_exposed[asymp_uids] + p.dur_asymp2rec.rvs(asymp_uids) / dt

        return

    def make_new_cases(self):
        """ Add indirect transmission """
        # Make new cases via direct transmission
        super().make_new_cases()
        
        # Make new cases via indirect transmission
        pars = self.pars
        res = self.results
        p_transmit = res.env_conc[self.sim.ti] * pars.beta_env
        pars.p_env_transmit.set(p=p_transmit)
        new_cases = pars.p_env_transmit.filter(self.sim.people.uid[self.susceptible]) # TODO: make syntax nicer
        if new_cases.any():
            self.set_prognoses(new_cases, source_uids=None)
        return

    def update_death(self, uids):
        """ Reset infected/recovered flags for dead agents """
        for state in ['susceptible', 'exposed', 'infected', 'symptomatic', 'recovered']:
            self.statesdict[state][uids] = False
        return

    def update_results(self):
        super().update_results()
        res = self.results
        ti = self.sim.ti
        res.new_deaths[ti] = np.count_nonzero(self.ti_dead == ti)
        res.cum_deaths[ti] = np.sum(res.new_deaths[:ti+1])
        return
