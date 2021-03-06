__author__ = 'Xinyue'

from cvxpy import *
from initial import rand_initial
from find_set import find_minimal_sets
from fix import fix
import cvxpy as cvx
import numpy as np

def is_dmcp(prob):
    """
    :param prob: a problem
    :return: a boolean indicating if the problem is DMCP
    """
    for var in prob.variables():
        fix_var = [avar for avar in prob.variables() if not avar.id == var.id]
        if not fix(prob,fix_var).is_dcp():
            return False
    return True


def bcd(prob, max_iter = 100, solver = 'SCS', mu = 5e-3, rho = 1.5, mu_max = 1e5, ep = 1e-3, lambd = 10, update = 'proximal'):
    """
    call the solving method
    :param prob: a problem
    :param max_iter: maximal number of iterations
    :param solver: DCP solver
    :param mu: initial value of parameter mu
    :param rho: increasing factor for mu
    :param mu_max: maximal value of mu
    :param ep: precision in convergence criterion
    :param lambd: parameter lambda
    :param update: update method
    :return: it: number of iterations; max_slack: maximum slack variable
    """
    # check if the problem is DMCP
    if not is_dmcp(prob):
        print "problem is not DMCP"
        return None
    # check if the problem is dcp
    if prob.is_dcp():
        print "problem is DCP"
        prob.solve()
    else:
        fix_sets = find_minimal_sets(prob)
        flag_ini = 0
        for var in prob.variables():
            if var.value is None: # check if initialization is needed
                flag_ini = 1
                rand_initial(prob)
                break
        # set update option
        if update == 'proximal':
            proximal = True
            linearize = False
        elif update == 'minimize':
            proximal = False
            linearize = False
        elif update == 'prox_linear':
            proximal = True
            linearize = True
        else:
            print "no such update method"
            return None
        result = _bcd(prob, fix_sets, max_iter, solver, mu, rho, mu_max, ep, lambd, linearize, proximal)
        # print result
        print "======= result ======="
        print "minimal sets:", fix_sets
        if flag_ini:
            print "initial point not set by the user"
        print "number of iterations:", result[0]+1
        print "maximum value of slack variables:", result[1]
        print "objective value:", prob.objective.value
        return result

def _bcd(prob, fix_sets, max_iter, solver, mu, rho, mu_max, ep, lambd, linear, proximal):
    """
    block coordinate descent
    :param prob: Problem
    :param max_iter: maximum number of iterations
    :param solver: solver used to solved each fixed problem
    :return: it: number of iterations; max_slack: maximum slack variable
    """
    obj_pre = np.inf
    for it in range(max_iter):
        np.random.shuffle(fix_sets)
        #print "======= iteration", it, "======="
        for set in fix_sets:
            #fix_set = [var for var in prob.variables() if var.id in set]
            fix_var = [prob.variables()[idx] for idx in set]
            # fix variables in fix_set
            fixed_p = fix(prob,fix_var)
            # linearize
            if linear:
                fixed_p.objective.args[0] = linearize(fixed_p.objective.args[0])
            # add slack variables
            fixed_p, var_slack = add_slack(fixed_p, mu)
            # proximal operator
            if proximal:
                fixed_p = proximal_op(fixed_p, var_slack, lambd)
            # solve
            fixed_p.solve(solver = solver)
            max_slack = 0
            if not var_slack == []:
                max_slack = np.max([np.max(abs(var).value) for var in var_slack])
                print "max abs slack =", max_slack, "mu =", mu, "original objective value =", prob.objective.args[0].value, "fixed objective value =",fixed_p.objective.args[0].value, "status=", fixed_p.status
            else:
                print "original objective value =", prob.objective.args[0].value, "status=", fixed_p.status
        mu = min(mu*rho, mu_max) # adaptive mu
        if np.linalg.norm(obj_pre - prob.objective.args[0].value) <= ep and max_slack<=ep: # quit
            return it, max_slack
        else:
            obj_pre = prob.objective.args[0].value
    return it, max_slack

def linearize(expr):
    """Returns the tangent approximation to the expression.
    Gives an elementwise lower (upper) bound for convex (concave)
    expressions. No guarantees for non-DCP expressions.
    Args:
        expr: An expression.
    Returns:
        An affine expression.
    """
    if expr.is_affine():
        return expr
    else:
        tangent = expr.value
        if tangent is None:
            raise ValueError(
        "Cannot linearize non-affine expression with missing variable values."
            )
        grad_map = expr.grad
        for var in expr.variables():
            if var.is_matrix():
                flattened = np.transpose(grad_map[var])*vec(var - var.value)
                tangent = tangent + reshape(flattened, *expr.size)
            else:
                if var.size[1] == 1:
                    tangent = tangent + np.transpose(grad_map[var])*(var - var.value)
                else:
                    tangent = tangent + (var - var.value)*grad_map[var]
        return tangent

def add_slack(prob, mu):
    """
    Add a slack variable to each constraint.
    For leq constraint, the slack variable is non-negative, and is on the right-hand side
    :param prob: a problem
    :param mu: weight of slack variables
    :return: a new problem with slack vars added, and the list of slack vars
    """
    var_slack = []
    new_constr = []
    for constr in prob.constraints:
        row = max([constr.args[0].size[0], constr.args[1].size[0]])
        col = max([constr.args[0].size[1], constr.args[1].size[1]])
        if constr.OP_NAME == "<=":
            var_slack.append(NonNegative(row,col)) # NonNegative slack var
            left = constr.args[0]
            right =  constr.args[1] + var_slack[-1]
            new_constr.append(left<=right)
        elif constr.OP_NAME == ">>":
            var_slack.append(NonNegative(1)) # NonNegative slack var
            left = constr.args[0] + var_slack[-1]*np.eye(row)
            right =  constr.args[1]
            new_constr.append(left>>right)
        else: # equality constraint
            var_slack.append(Variable(row,col))
            left = constr.args[0]
            right =  constr.args[1] + var_slack[-1]
            new_constr.append(left==right)
    new_cost = prob.objective.args[0]
    if prob.objective.NAME == 'minimize':
        for var in var_slack:
            new_cost  =  new_cost + norm(var,1)*mu
        new_prob = Problem(Minimize(new_cost), new_constr)
    else: # maximize
        for var in var_slack:
            new_cost  =  new_cost - norm(var,1)*mu
        new_prob = Problem(Maximize(new_cost), new_constr)
    return new_prob, var_slack

def proximal_op(prob, var_slack, lambd):
    """
    proximal operator of the objective
    :param prob: problem
    :param var_slack: slack variables
    :param lambd: proximal operator parameter
    :return: a problem with proximal operator
    """
    new_cost = prob.objective.args[0]
    slack_id = [var.id for var in var_slack]
    for var in prob.variables():
        # add quadratic terms for all variables that are not slacks
        if not var.id in slack_id:
            new_cost = new_cost + square(norm(var - var.value,'fro'))/2/lambd
    prob.objective.args[0] = new_cost
    return prob

cvx.Problem.register_solve("bcd", bcd)