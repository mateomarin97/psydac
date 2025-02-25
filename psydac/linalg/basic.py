# coding: utf-8
#
# Copyright 2018 Yaman Güçlü, Jalal Lakhlili
# Copyright 2022 Yaman Güçlü, Said Hadjout, Julian Owezarek
"""
provides the fundamental classes for linear algebra operations.

"""

from abc import ABC, abstractmethod
from types import LambdaType 
from inspect import signature

import numpy as np
import itertools
from scipy import sparse
from psydac.linalg.kernels.toarray_kernels import write_out_stencil_dense_3D, write_out_stencil_dense_2D, write_out_stencil_dense_1D, write_out_block_dense_3D, write_out_block_dense_2D, write_out_block_dense_1D


from psydac.utilities.utils import is_real

__all__ = (
    'VectorSpace',
    'Vector',
    'LinearOperator',
    'ZeroOperator',
    'IdentityOperator',
    'ScaledLinearOperator',
    'SumLinearOperator',
    'ComposedLinearOperator',
    'PowerLinearOperator',
    'InverseLinearOperator',
    'LinearSolver',
    'MatrixFreeLinearOperator'
)

#===============================================================================
class VectorSpace(ABC):
    """
    Finite-dimensional vector space V with a scalar (dot) product.

    """
    @property
    @abstractmethod
    def dimension(self):
        """
        The dimension of a vector space V is the cardinality
        (i.e. the number of vectors) of a basis of V over its base field.

        """

    @property
    @abstractmethod
    def dtype(self):
        """
        The data type of the field over which the space is built.

        """

    @abstractmethod
    def zeros(self):
        """
        Get a copy of the null element of the vector space V.

        Returns
        -------
        null : Vector
            A new vector object with all components equal to zero.

        """

#    @abstractmethod
    def dot(self, a, b):
        """
        Evaluate the scalar product between two vectors of the same space.

        """

    @abstractmethod
    def axpy(self, a, x, y):
        """
        Increment the vector y with the a-scaled vector x, i.e. y = a * x + y,
        provided that x and y belong to the same vector space V (self).
        The scalar value a may be real or complex, depending on the field of V.

        Parameters
        ----------
        a : scalar
            The scaling coefficient needed for the operation.

        x : Vector
            The vector which is not modified by this function.

        y : Vector
            The vector modified by this function (incremented by a * x).
        """

#===============================================================================
class Vector(ABC):
    """
    Element of a vector space V.

    """
    @property
    def shape(self):
        """ A tuple containing the dimension of the space. """
        return (self.space.dimension, )

    @property
    def dtype(self):
        """ The data type of the vector field V this vector belongs to. """
        return self.space.dtype

    def dot(self, v):
        """
        Evaluate the scalar product with the vector v of the same space.

        Parameters
        ----------
        v : Vector
            Vector belonging to the same space as self.

        """
        assert isinstance(v, Vector)
        assert self.space is v.space
        return self.space.dot(self, v)

    def mul_iadd(self, a, v):
        """
        Compute self += a * v, where v is another vector of the same space.

        Parameters
        ----------
        a : scalar
            Rescaling coefficient, which can be cast to the correct dtype.

        v : Vector
            Vector belonging to the same space as self.
        """
        self.space.axpy(a, v, self)

    #-------------------------------------
    # Deferred methods
    #-------------------------------------
    @property
    @abstractmethod
    def space(self):
        """ Vector space to which this vector belongs. """

    @abstractmethod
    def toarray(self, **kwargs):
        """ Convert to Numpy 1D array. """

    @abstractmethod
    def copy(self, out=None):
        """Ensure x.copy(out=x) returns x and not a new object."""
        pass

    @abstractmethod
    def __neg__(self):
        pass

    @abstractmethod
    def __mul__(self, a):
        pass

    @abstractmethod
    def __add__(self, v):
        pass

    @abstractmethod
    def __sub__(self, v):
        pass

    @abstractmethod
    def __imul__(self, a):
        pass

    @abstractmethod
    def __iadd__(self, v):
        pass

    @abstractmethod
    def __isub__(self, v):
        pass

    @abstractmethod
    def conjugate(self, out=None):
        """Compute the complex conjugate vector.

        If the field is real (i.e. `self.dtype in (np.float32, np.float64)`) this method is equivalent to `copy`.
        If the field is complex (i.e. `self.dtype in (np.complex64, np.complex128)`) this method returns
        the complex conjugate of `self`, element-wise.

        The behavior of this function is similar to `numpy.conjugate(self, out=None)`.
        """

    #-------------------------------------
    # Methods with default implementation
    #-------------------------------------
    def __rmul__(self, a):
        return self * a

    def __truediv__(self, a):
        return self * (1.0 / a)

    def __itruediv__(self, a):
        self *= 1.0 / a
        return self

    def conj(self, out=None):
        """Compute the complex conjugate vector.

        If the field is real (i.e. `self.dtype in (np.float32, np.float64)`) this method is equivalent to `copy`.
        If the field is complex (i.e. `self.dtype in (np.complex64, np.complex128)`) this method returns
        the complex conjugate of `self`, element-wise.

        The behavior of this function is similar to `numpy.conj(self, out=None)`.
        """
        return self.conjugate(out)

#===============================================================================
class LinearOperator(ABC):
    """
    Abstract base class for all linear operators acting between two vector spaces V (domain)
    and W (codomain).

    """
    @property
    def shape(self):
        """ A tuple containing the dimension of the codomain and domain. """
        return (self.codomain.dimension, self.domain.dimension)

    #-------------------------------------
    # Deferred methods
    #-------------------------------------
    @property
    @abstractmethod
    def domain(self):
        """ The domain of the linear operator - an element of Vectorspace """
        pass

    @property
    @abstractmethod
    def codomain(self):
        """ The codomain of the linear operator - an element of Vectorspace """
        pass

    @property
    @abstractmethod
    def dtype(self):
        pass
    
    def __tosparse_array(self, out=None, is_sparse=False):
        """
        Transforms the linear operator into a matrix, which is either stored in dense or sparse format.

        Parameters
        ----------
        out : Numpy.ndarray, optional
            If given, the output will be written in-place into this array.
        is_sparse : bool, optional
            If set to True the method returns the matrix as a Scipy sparse matrix, if set to false
            it returns the full matrix as a Numpy.ndarray

        Returns
        -------
        out : Numpy.ndarray or scipy.sparse.csr.csr_matrix
            The matrix form of the linear operator. If ran in parallel each rank gets the full
            matrix representation of the linear operator.
        """
        # v will be the unit vector with which we compute Av = ith column of A.
        v = self.domain.zeros()
        # We define a temporal vector
        tmp2 = self.codomain.zeros()

        #We need to determine if we are a blockvector or a stencilvector but we are not able to use 
        #the BlockVectorSpace and StencilVectorSpace classes in here. So we check if domain has the spaces
        #attribute in which case the domain would be a BlockVectorSpace. If that is not the case we check
        #if the domain has the cart atrribute, in which case it will be a StencilVectorSpace.
        if  hasattr(self.domain, 'spaces'):
            BoS = "b"
        elif hasattr(self.domain, 'cart'):
            BoS = "s"
        else:
            raise Exception(
                'The domain of the LinearOperator must be a BlockVectorSpace or a StencilVectorSpace.')
               
        #We also need to know if the codomain is a StencilVectorSpace or a BlockVectorSpace
        if  hasattr(self.codomain, 'spaces'):
            BoS2 = "b"
        elif hasattr(self.codomain, 'cart'):
            BoS2 = "s"
        else:
            raise Exception(
                'The codomain of the LinearOperator must be a BlockVectorSpace or a StencilVectorSpace.')
        
        if BoS == "b":
            comm = self.domain.spaces[0].cart.comm
        elif BoS == "s":
            comm = self.domain.cart.comm
        rank = comm.Get_rank()
        size = comm.Get_size()

        if (is_sparse == False):
            if out is None:
                # We declare the matrix form of our linear operator
                out = np.zeros(
                    [self.codomain.dimension, self.domain.dimension], dtype=self.dtype)
            else:
                assert isinstance(out, np.ndarray)
                assert out.shape[0] == self.codomain.dimension
                assert out.shape[1] == self.domain.dimension
        else:
            if out is not None:
                raise Exception(
                    'If is_sparse is True then out must be set to None.')
            numrows = self.codomain.dimension
            numcols = self.domain.dimension
            # We define a list to store the non-zero data, a list to sotre the row index of said data and a list to store the column index.
            data = []
            row = []
            colarr = []

        # V is either a BlockVector or a StencilVector depending on the domain of the linear operator.
        if BoS == "b":
            # we collect all starts and ends in two big lists
            starts = [vi.starts for vi in v]
            ends = [vi.ends for vi in v]
            # We collect the dimension of the BlockVector
            npts = [sp.npts for sp in self.domain.spaces]
            # We get the number of space we have
            nsp = len(self.domain.spaces)
            # We get the number of dimensions each space has.
            ndim = [sp.ndim for sp in self.domain.spaces]
        elif BoS == "s":
            # We get the start and endpoint for each sublist in v
            starts = [v.starts]
            ends = [v.ends]
            # We get the dimensions of the StencilVector
            npts = [self.domain.npts]
            # We get the number of space we have
            nsp = 1
            # We get the number of dimensions the StencilVectorSpace has.
            ndim = [self.domain.ndim]
            
        # First each rank is going to need to know the starts and ends of all other ranks
        startsarr = np.array([starts[i][j] for i in range(nsp)
                                for j in range(ndim[i])], dtype=int)
        
        endsarr = np.array([ends[i][j] for i in range(nsp)
                            for j in range(ndim[i])], dtype=int) 
            
        # Create an array to store gathered data from all ranks
        allstarts = np.empty(size * len(startsarr), dtype=int)

        # Use Allgather to gather 'starts' from all ranks into 'allstarts'
        comm.Allgather(startsarr, allstarts)

        # Reshape 'allstarts' to have 9 columns and 'size' rows
        allstarts = allstarts.reshape((size, len(startsarr)))

        # Create an array to store gathered data from all ranks
        allends = np.empty(size * len(endsarr), dtype=int)

        # Use Allgather to gather 'ends' from all ranks into 'allends'
        comm.Allgather(endsarr, allends)

        # Reshape 'allends' to have 9 columns and 'size' rows
        allends = allends.reshape((size, len(endsarr)))

        
        # Before we begin computing the dot products we need to know which entries of the output vector tmp2 belong to our rank.
        if BoS2 == "s":
            # We get the start and endpoint for each sublist in tmp2
            starts2 = tmp2.starts
            ends2 = tmp2.ends
            # We get the dimensions of the StencilVector
            npts2 = np.array(self.codomain.npts)
            # We get the number of space we have
            nsp2 = 1
            # We get the number of dimensions the StencilVectorSpace has.
            ndim2 = self.codomain.ndim
            #We build our ranges of iteration
            if (is_sparse == False):
                itterables2 = []
                for ii in range(ndim2):
                    itterables2.append([starts2[ii], ends2[ii]+1])
                    #itterables2.append(range(starts2[ii], ends2[ii]+1))
                itterables2 = np.array(itterables2)
                #We also get the StencilVector's pads
                pds = np.array(tmp2.pads)
            else:
                itterables2 = []
                for ii in range(ndim2):
                    itterables2.append(
                        range(starts2[ii], ends2[ii]+1))
                
        elif BoS2 == "b":
            # we collect all starts and ends in two big lists
            starts2 = [vi.starts for vi in tmp2]
            ends2 = [vi.ends for vi in tmp2]
            # We collect the dimension of the BlockVector
            npts2 = np.array([sp.npts for sp in self.codomain.spaces])
            # We get the number of space we have
            nsp2 = len(self.codomain.spaces)
            # We get the number of dimensions each space has.
            ndim2 = [sp.ndim for sp in self.codomain.spaces]
            if (is_sparse == False):
                #We also get the BlockVector's pads
                pds = np.array([vi.pads for vi in tmp2])
                #We build the range of iteration
                itterables2 = []
                # since the size of npts changes denpending on h we need to compute a starting point for
                # our row index
                spoint2 = 0
                spoint2list = [np.int64(spoint2)]
                for hh in range(nsp2):
                    itterables2aux = []
                    for ii in range(ndim2[hh]):
                        itterables2aux.append(
                            [starts2[hh][ii], ends2[hh][ii]+1])
                    itterables2.append(itterables2aux)
                    cummulative2 = 1
                    for ii in range(ndim2[hh]):
                        cummulative2 *= npts2[hh][ii]
                    spoint2 += cummulative2
                    spoint2list.append(spoint2) 
            else:
                itterables2 = []
                # since the size of npts changes denpending on h we need to compute a starting point for
                # our row index
                spoint2 = 0
                spoint2list = [spoint2]
                for hh in range(nsp2):
                    itterables2aux = []
                    for ii in range(ndim2[hh]):
                        itterables2aux.append(
                            range(starts2[hh][ii], ends2[hh][ii]+1))
                    itterables2.append(itterables2aux)
                    cummulative2 = 1
                    for ii in range(ndim2[hh]):
                        cummulative2 *= npts2[hh][ii]
                    spoint2 += cummulative2
                    spoint2list.append(spoint2)


        currentrank = 0
        # Each rank will take care of setting to 1 each one of its entries while all other entries remain zero.
        while (currentrank < size):
            # since the size of npts changes denpending on h we need to compute a starting point for
            # our column index
            spoint = 0
            npredim = 0
            # We iterate over the stencil vectors inside the BlockVector
            for h in range(nsp):
                itterables = []
                for i in range(ndim[h]):
                    itterables.append(
                        range(allstarts[currentrank][i+npredim], allends[currentrank][i+npredim]+1))
                # We iterate over all the entries that belong to rank number currentrank
                for i in itertools.product(*itterables):
                    
                    #########################################
                    if BoS == "b":
                        if (rank == currentrank):
                            v[h][i] = 1.0
                        v[h].update_ghost_regions()
                    elif BoS == "s":
                        if (rank == currentrank):
                            v[i] = 1.0
                        v.update_ghost_regions()
                    #########################################
                    
                    # Compute dot product with the linear operator.
                    self.dot(v, out=tmp2)
                    # Compute to which column this iteration belongs
                    col = spoint
                    col += np.ravel_multi_index(i, npts[h])
                    
                    # Case in which tmp2 is a StencilVector
                    if BoS2 == "s":
                        if is_sparse == False:
                            #We iterate over the entries of tmp2 that belong to our rank
                            #The pyccel kernels are tantamount to this for loop.
                            #for ii in itertools.product(*itterables2):
                                #if (tmp2[ii] != 0):
                                    #out[np.ravel_multi_index(
                                        #ii, npts2), col] = tmp2[ii]
                            if (ndim2 == 3):
                                write_out_stencil_dense_3D(itterables2, tmp2._data, out, npts2, col, pds)
                            elif (ndim2 == 2):
                                write_out_stencil_dense_2D(itterables2, tmp2._data, out, npts2, col, pds)
                            elif (ndim2 == 1):
                                write_out_stencil_dense_1D(itterables2, tmp2._data, out, npts2, col, pds)
                            else:
                                raise Exception("The codomain dimension must be 3, 2 or 1.")
                            
                        else:
                            #We iterate over the entries of tmp2 that belong to our rank
                            for ii in itertools.product(*itterables2):
                                if (tmp2[ii] != 0):
                                    data.append(tmp2[ii])
                                    colarr.append(col)
                                    row.append(
                                        np.ravel_multi_index(ii, npts2))
                    elif BoS2 =="b":
                        # We iterate over the stencil vectors inside the BlockVector
                        for hh in range(nsp2):
                            
                            
                            if is_sparse == False:
                                itterables2aux = np.array(itterables2[hh])
                                # We iterate over all the tmp2 entries that belong to rank number currentrank
                                #for ii in itertools.product(*itterables2aux):
                                    #if (tmp2[hh][ii] != 0):
                                        #out[spoint2list[hh]+np.ravel_multi_index(
                                            #ii, npts2[hh]), col] = tmp2[hh][ii]
                                if (ndim2[hh] == 3):
                                    write_out_block_dense_3D(itterables2aux, tmp2[hh]._data, out, npts2[hh], col, pds[hh], spoint2list[hh])
                                elif (ndim2[hh] == 2):
                                    write_out_block_dense_2D(itterables2aux, tmp2[hh]._data, out, npts2[hh], col, pds[hh], spoint2list[hh])
                                elif (ndim2[hh] == 1):
                                    write_out_block_dense_1D(itterables2aux, tmp2[hh]._data, out, npts2[hh], col, pds[hh], spoint2list[hh])
                                else:
                                    raise Exception("The codomain dimension must be 3, 2 or 1.")
                            else:
                                itterables2aux = itterables2[hh]
                                for ii in itertools.product(*itterables2aux):
                                    if (tmp2[hh][ii] != 0):
                                        data.append(tmp2[hh][ii])
                                        colarr.append(col)
                                        row.append(
                                            spoint2list[hh]+np.ravel_multi_index(ii, npts2[hh]))        
                    #################################
                    if BoS == "b":
                        if (rank == currentrank):
                            v[h][i] = 0.0
                        v[h].update_ghost_regions()
                    elif BoS == "s":
                        if (rank == currentrank):
                            v[i] = 0.0
                        v.update_ghost_regions()
                    ##################################
                cummulative = 1
                for i in range(ndim[h]):
                    cummulative *= npts[h][i]
                spoint += cummulative
                npredim += ndim[h]
            currentrank += 1
        
        if is_sparse == False:
            return out
        else:
            return sparse.csr_matrix((data, (row, colarr)), shape=(numrows, numcols))
    
    
    # Function that returns the local matrix corresponding to the linear operator. Returns a scipy.sparse.csr.csr_matrix.
    def tosparse(self):
        """
        Transforms the linear operator into a matrix, which is stored in sparse csr format.

        Returns
        -------
        out : Numpy.ndarray or scipy.sparse.csr.csr_matrix
            The matrix form of the linear operator. If ran in parallel each rank gets the local
            matrix representation of the linear operator.
        """
        return self.__tosparse_array(is_sparse=True)
    
    
    # Function that returns the matrix corresponding to the linear operator. Returns a numpy array.
    def toarray(self, out=None):
        """
        Transforms the linear operator into a matrix, which is stored in dense format.

        Parameters
        ----------
        out : Numpy.ndarray, optional
            If given, the output will be written in-place into this array.
            
        Returns
        -------
        out : Numpy.ndarray
            The matrix form of the linear operator. If ran in parallel each rank gets the local
            matrix representation of the linear operator.
        """
        return self.__tosparse_array(out=out, is_sparse=False)

    
    @abstractmethod
    def dot(self, v, out=None):
        """ Apply linear operator to Vector v. Result is written to Vector out, if provided."""
        pass

    @abstractmethod
    def transpose(self, conjugate=False):
        """
        Transpose the LinearOperator .

        If conjugate is True, return the Hermitian transpose.
        """
        pass

    # TODO: check if we should add a copy method!!!

    #-------------------------------------
    # Magic methods
    #-------------------------------------
    def __neg__(self):
        """
        Scales itself by -1 and thus returns the addititive inverse as 
        a new object of the class ScaledLinearOperator.
        
        """
        return ScaledLinearOperator(self.domain, self.codomain, -1.0, self)

    def __mul__(self, c):
        """
        Scales a linear operator by a real scalar c by creating an object of the class ScaledLinearOperator,
        unless c = 0 or c = 1, in which case either a ZeroOperator or self is returned.

        """
        assert np.isscalar(c)
        assert np.isreal(c)
        if c==0:
            return ZeroOperator(self.domain, self.codomain)
        elif c == 1:
            return self
        else:
            return ScaledLinearOperator(self.domain, self.codomain, c, self)

    def __rmul__(self, c):
        """ Calls __mul__ instead. """
        return self * c

    def __matmul__(self, B):
        """ Creates an object of the class ComposedLinearOperator. """
        assert isinstance(B, (LinearOperator, Vector))
        if isinstance(B, LinearOperator):
            assert self.domain == B.codomain
            if isinstance(B, ZeroOperator):
                return ZeroOperator(B.domain, self.codomain)
            elif isinstance(B, IdentityOperator):
                return self
            else:
                return ComposedLinearOperator(B.domain, self.codomain, self, B)
        else:
            return self.dot(B)

    def __add__(self, B):
        """ Creates an object of the class SumLinearOperator unless B is a ZeroOperator in which case self is returned. """
        assert isinstance(B, LinearOperator)
        if isinstance(B, ZeroOperator):
            return self
        else:
            return SumLinearOperator(self.domain, self.codomain, self, B)

    def __sub__(self, B):
        """ Creates an object of the class SumLinearOperator unless B is a ZeroOperator in which case self is returned. """
        assert isinstance(B, LinearOperator)
        if isinstance(B, ZeroOperator):
            return self
        else:
            return SumLinearOperator(self.domain, self.codomain, self, -B)

    def __pow__(self, n):
        """ Creates an object of class :ref:`PowerLinearOperator <powerlinearoperator>`. """
        return PowerLinearOperator(self.domain, self.codomain, self, n)

    def __truediv__(self, c):
        """ Divide by scalar. """
        return self * (1.0 / c)

    def __itruediv__(self, c):
        """ Divide by scalar, in place. """
        self *= 1.0 / c
        return self

    #-------------------------------------
    # Methods with default implementation
    #-------------------------------------

    @property
    def T(self):
        """ Calls transpose method to return the transpose of self. """
        return self.transpose()

    @property
    def H(self):
        """ Calls transpose method with `conjugate=True` flag to return the Hermitian transpose of self. """
        return self.transpose(conjugate=True)

    def idot(self, v, out):
        """
        Implements out += self @ v with a temporary.
        Subclasses should provide an implementation without a temporary.

        """
        assert isinstance(v, Vector)
        assert v.space == self.domain
        assert isinstance(out, Vector)
        assert out.space == self.codomain
        out += self.dot(v)

#===============================================================================
class ZeroOperator(LinearOperator):
    """
    Zero operator mapping any vector from its domain V to the zero vector of its codomain W.
    
    """

    def __new__(cls, domain, codomain=None):

        assert isinstance(domain, VectorSpace)
        assert isinstance(codomain, VectorSpace)

        from psydac.linalg.block import BlockVectorSpace, BlockLinearOperator
        if isinstance(domain, BlockVectorSpace) or isinstance(codomain, BlockVectorSpace):
            if isinstance(domain, BlockVectorSpace):
                domain_spaces = domain.spaces
            else:
                domain_spaces = (domain,)
            if isinstance(codomain, BlockVectorSpace):
                codomain_spaces = codomain.spaces
            else:
                codomain_spaces = (codomain,)
            blocks = {}
            for i, D in enumerate(domain_spaces):
                for j, C in enumerate(codomain_spaces):
                    blocks[j,i] = ZeroOperator(D,C)
            return BlockLinearOperator(domain, codomain, blocks)
        else:
            return super().__new__(cls)
    
    def __init__(self, domain, codomain):

        self._domain = domain
        self._codomain = codomain

    @property
    def domain(self):
        return self._domain

    @property
    def codomain(self):
        return self._codomain

    @property
    def dtype(self):
        return None

    def copy(self):
        return ZeroOperator(self.domain, self.codomain)

    def toarray(self):
        return np.zeros(self.shape, dtype=self.dtype) 

    def tosparse(self):
        from scipy.sparse import csr_matrix
        return csr_matrix(self.shape, dtype=self.dtype)

    def transpose(self, conjugate=False):
        return ZeroOperator(domain=self.codomain, codomain=self.domain)

    def dot(self, v, out=None):
        assert isinstance(v, Vector)
        assert v.space == self.domain
        if out is not None:
            assert isinstance(out, Vector)
            assert out.space == self.codomain
            out *= 0
        else:
            out = self.codomain.zeros()
        return out

    def __neg__(self):
        return self

    def __add__(self, B):
        assert isinstance(B, LinearOperator)
        assert self.domain == B.domain
        assert self.codomain == B.codomain
        return B

    def __sub__(self, B):
        assert isinstance(B, LinearOperator)
        assert self.domain == B.domain
        assert self.codomain == B.codomain
        return -B

    def __mul__(self, c):
        assert np.isscalar(c)
        return self

    def __matmul__(self, B):
        assert isinstance(B, (LinearOperator, Vector))
        if isinstance(B, LinearOperator):
            assert self.domain == B.codomain
            return ZeroOperator(domain=B.domain, codomain=self.codomain)
        else:
            return self.dot(B)

#===============================================================================
class IdentityOperator(LinearOperator):
    """
    Identity operator acting between a vector space V and itself.
    Useful for example in custom linear operator classes together with the apply_essential_bc method to create projection operators.
    
    """

    def __init__(self, domain, codomain=None):

        assert isinstance(domain, VectorSpace)
        if codomain:
            assert isinstance(codomain, VectorSpace)
            assert domain == codomain

        self._domain = domain
        self._codomain = domain

    @property
    def domain(self):
        return self._domain

    @property
    def codomain(self):
        return self._codomain

    @property
    def dtype(self):
        return None

    def copy(self):
        """ Returns a new IdentityOperator object acting between the same vector spaces."""
        return IdentityOperator(self.domain, self.codomain)

    def toarray(self):
        return np.diag(np.ones(self.domain.dimension , dtype=self.dtype)) 

    def tosparse(self):
        from scipy.sparse import identity
        return identity(self.domain.dimension, dtype=self.dtype, format="csr")

    def transpose(self, conjugate=False):
        """ Could return self, but by convention returns new object. """
        return IdentityOperator(self.domain, self.codomain)

    def dot(self, v, out=None):
        assert isinstance(v, Vector)
        assert v.space == self.domain
        if out is not None:
            assert isinstance(out, Vector)
            assert out.space == self.codomain
            out *= 0
            out += v
            return out
        else:
            return v.copy()

    def __matmul__(self, B):
        assert isinstance(B, (LinearOperator, Vector))
        if isinstance(B, LinearOperator):
            assert self.domain == B.codomain
            return B
        else:
            return self.dot(B)

#===============================================================================
class ScaledLinearOperator(LinearOperator):
    """
    A linear operator $A$ scalar multiplied by a real constant $c$. 
    
    """

    def __init__(self, domain, codomain, c, A):

        assert isinstance(domain, VectorSpace)
        assert isinstance(codomain, VectorSpace)
        assert np.isscalar(c)
        assert np.isreal(c)
        assert isinstance(A, LinearOperator)
        assert domain   == A.domain
        assert codomain == A.codomain

        if isinstance(A, ScaledLinearOperator):
            scalar = A.scalar * c
            operator = A.operator
        else:
            scalar = c
            operator = A

        self._operator = operator
        self._scalar   = scalar
        self._domain   = domain
        self._codomain = codomain

    @property
    def domain(self):
        return self._domain

    @property
    def codomain(self):
        return self._codomain

    @property
    def scalar(self):
        """ Returns the scalar value by which the operator is multiplied."""
        return self._scalar

    @property
    def operator(self):
        """ Returns the operator that is multiplied by the scalar."""
        return self._operator

    @property
    def dtype(self):
        return None

    def toarray(self):
        return self._scalar*self._operator.toarray() 

    def tosparse(self):
        from scipy.sparse import csr_matrix
        return self._scalar*csr_matrix(self._operator.toarray())

    def transpose(self, conjugate=False):
        return ScaledLinearOperator(domain=self.codomain, codomain=self.domain, c=self._scalar, A=self._operator.transpose(conjugate=conjugate))

    def __neg__(self):
        return ScaledLinearOperator(domain=self.domain, codomain=self.codomain, c=-1*self._scalar, A=self._operator)

    def dot(self, v, out=None):
        assert isinstance(v, Vector)
        assert v.space == self.domain
        if out is not None:
            assert isinstance(out, Vector)
            assert out.space == self.codomain
            self._operator.dot(v, out = out)
            out *= self._scalar
            return out
        else:
            out = self._operator.dot(v)
            out *= self._scalar
            return out

#===============================================================================
class SumLinearOperator(LinearOperator):
    """
    Sum $\sum_{i=1}^n A_i$ of linear operators $A_1,\dots,A_n$ acting between the same vector spaces V (domain) and W (codomain).

    """
    def __new__(cls, domain, codomain, *args):

        if len(args) == 0:
            return ZeroOperator(domain,codomain)
        elif len(args) == 1:
            return args[0]
        else:
            return super().__new__(cls)

    def __init__(self, domain, codomain, *args):

        assert isinstance(domain, VectorSpace)
        assert isinstance(codomain, VectorSpace)
        for a in args:
            assert isinstance(a, LinearOperator)
            assert a.domain == domain
            assert a.codomain == codomain

        addends = ()
        for a in args:
            if isinstance(a, SumLinearOperator):
                addends = (*addends, *a.addends)
            else:
                addends = (*addends, a)

        addends = SumLinearOperator.simplify(addends)

        self._domain = domain
        self._codomain = codomain
        self._addends = addends

    @property
    def domain(self):
        """ The domain of the linear operator, element of class ``VectorSpace``. """
        return self._domain

    @property
    def codomain(self):
        """ The codomain of the linear operator, element of class ``VectorSpace``. """
        return self._codomain

    @property
    def addends(self):
        """ A tuple containing the addends of the linear operator, elements of class ``LinearOperator``. """
        return self._addends

    @property
    def dtype(self):
        return None

    def toarray(self):
        out = np.zeros(self.shape, dtype=self.dtype)
        for a in self._addends:
            out += a.toarray()
        return out

    def tosparse(self):
        from scipy.sparse import csr_matrix
        out = csr_matrix(self.shape, dtype=self.dtype)
        for a in self._addends:
            out += a.tosparse()
        return out

    def transpose(self, conjugate=False):
        t_addends = ()
        for a in self._addends:
            t_addends = (*t_addends, a.transpose(conjugate=conjugate))
        return SumLinearOperator(self.codomain, self.domain, *t_addends)

    @staticmethod
    def simplify(addends):
        """ Simplifies a sum of linear operators by combining addends of the same class. """
        class_list  = [a.__class__ for a in addends]
        unique_list = [*{c: a for c, a in zip(class_list, addends)}]
        if len(unique_list) == 1:
            return addends
        out = ()
        for j in unique_list:
            indices = [k for k, l in enumerate(class_list) if l == j]
            if len(indices) == 1:
                out = (*out, addends[indices[0]])
            else:
                A = addends[indices[0]] + addends[indices[1]]
                for n in range(len(indices)-2):
                    A += addends[indices[n+2]]
                if isinstance(A, SumLinearOperator):
                    out = (*out, *A.addends)
                else:
                    out = (*out, A)
        return out

    def dot(self, v, out=None):
        """ Evaluates SumLinearOperator object at a vector v element of domain. """
        assert isinstance(v, Vector)
        assert v.space == self.domain
        if out is not None:
            assert isinstance(out, Vector)
            assert out.space == self.codomain
            out *= 0
            for a in self._addends:
                a.idot(v, out)
            return out
        else:
            out = self.codomain.zeros()
            for a in self._addends:
                a.idot(v, out=out)
            return out

#===============================================================================
class ComposedLinearOperator(LinearOperator):
    """
    Composition $A_n\circ\dots\circ A_1$ of two or more linear operators $A_1,\dots,A_n$.
    
    """

    def __init__(self, domain, codomain, *args):

        assert isinstance(domain, VectorSpace)
        assert isinstance(codomain, VectorSpace)

        for a in args:
            assert isinstance(a, LinearOperator)
        assert args[0].codomain == codomain
        assert args[-1].domain == domain

        for i in range(len(args)-1):
            assert args[i].domain == args[i+1].codomain

        multiplicants = ()
        tmp_vectors = []
        for a in args[:-1]:
            if isinstance(a, ComposedLinearOperator):
                multiplicants = (*multiplicants, *a.multiplicants)
                tmp_vectors.extend(a.tmp_vectors)
                tmp_vectors.append(a.domain.zeros())
            else:
                multiplicants = (*multiplicants, a)
                tmp_vectors.append(a.domain.zeros())

        last = args[-1]
        if isinstance(last, ComposedLinearOperator):
            multiplicants = (*multiplicants, *last.multiplicants)
            tmp_vectors.extend(last.tmp_vectors)
        else:
            multiplicants = (*multiplicants, last)

        self._domain = domain
        self._codomain = codomain
        self._multiplicants = multiplicants
        self._tmp_vectors = tuple(tmp_vectors)

    @property
    def tmp_vectors(self):
        """
        A tuple containing the storage vectors that are repeatedly being used upon calling the `dot` method.
        This avoids the creation of new vectors at each call of the `dot` method.
        
        """
        return self._tmp_vectors

    @property
    def domain(self):
        return self._domain

    @property
    def codomain(self):
        return self._codomain

    @property
    def multiplicants(self):
        """
        A tuple $(A_1,\dots,A_n)$ containing the multiplicants of the linear operator 
        $self = A_n\circ\dots\circ A_1$.
        
        """
        return self._multiplicants

    @property
    def dtype(self):
        return None

    def tosparse(self):
        mats = [M.tosparse() for M in self._multiplicants]
        M = mats[0]
        for Mi in mats[1:]:
            M = M @ Mi
        return sparse.coo_matrix(M)

    def transpose(self, conjugate=False):
        t_multiplicants = ()
        for a in self._multiplicants:
            t_multiplicants = (a.transpose(conjugate=conjugate), *t_multiplicants)
        new_dom = self.codomain
        new_cod = self.domain
        assert isinstance(new_dom, VectorSpace)
        assert isinstance(new_cod, VectorSpace)
        return ComposedLinearOperator(self.codomain, self.domain, *t_multiplicants)

    def dot(self, v, out=None):
        assert isinstance(v, Vector)
        assert v.space == self.domain
        if out is not None:
            assert isinstance(out, Vector)
            assert out.space == self.codomain

        x = v
        for i in range(len(self._tmp_vectors)):
            y = self._tmp_vectors[-1-i]
            A = self._multiplicants[-1-i]
            A.dot(x, out=y)
            x = y

        A = self._multiplicants[0]
        if out is not None:

            A.dot(x, out=out)
        else:
            out = A.dot(x)
        return out

    def exchange_assembly_data(self):
        for op in self._multiplicants:
            op.exchange_assembly_data()

    def set_backend(self, backend):
        for op in self._multiplicants:
            op.set_backend(backend)

#===============================================================================
class PowerLinearOperator(LinearOperator):
    """
    Power $A^n$ of a linear operator $A$ for some integer $n\geq 0$.
    
    """

    def __new__(cls, domain, codomain, A, n):

        assert isinstance(n, int)
        assert n >= 0

        assert isinstance(A, LinearOperator)
        assert A.domain == domain
        assert A.codomain == codomain
        assert domain == codomain

        if n == 0:
            return IdentityOperator(domain, codomain)
        elif n == 1:
            return A
        else:
            return super().__new__(cls)

    def __init__(self, domain, codomain, A, n):

        if isinstance(A, PowerLinearOperator):
            self._operator = A.operator
            self._factorial = A.factorial*n
        else:
            self._operator = A
            self._factorial = n
        self._domain = domain
        self._codomain = codomain

    @property
    def domain(self):
        return self._domain

    @property
    def codomain(self):
        return self._codomain

    @property
    def dtype(self):
        return None

    @property
    def operator(self):
        """ Returns the operator that is raised to the power. """
        return self._operator

    @property
    def factorial(self):
        """ Returns the power to which the operator is raised. """
        return self._factorial

    def transpose(self, conjugate=False):
        return PowerLinearOperator(domain=self.codomain, codomain=self.domain, A=self._operator.transpose(conjugate=conjugate), n=self._factorial)

    def dot(self, v, out=None):
        assert isinstance(v, Vector)
        assert v.space == self.domain
        if out is not None:
            assert isinstance(out, Vector)
            assert out.space == self.codomain
            for i in range(self._factorial):
                self._operator.dot(v, out=out)
                v = out.copy()
        else:
            out = v.copy()
            for i in range(self._factorial):
                out = self._operator.dot(out)
        return out

#===============================================================================
class InverseLinearOperator(LinearOperator):
    """
    Abstract base class for the (approximate) inverse $A^{-1}$ of a
    square matrix $A$. The result of A_inv.dot(b) is the (approximate) solution x
    of the linear system A x = b, where x and b belong to the same vector space V.

    We assume that the linear system is solved by an iterative method, which
    needs a first guess `x0` and an exit condition based on `tol` and `maxiter`.

    Concrete subclasses of this class must implement the `dot` method and take
    care of any internal storage which might be necessary.

    Parameters
    ----------
    A : psydac.linalg.basic.LinearOperator
        Left-hand-side matrix A of linear system.
        
    x0 : psydac.linalg.basic.Vector
        First guess of solution for iterative solver (optional).
        
    tol : float
        Absolute tolerance for L2-norm of residual r = A*x - b.
        
    maxiter: int
        Maximum number of iterations.
        
    verbose : bool
        If True, L2-norm of residual r is printed at each iteration.
    """

    def __init__(self, A, **kwargs):

        assert isinstance(A, LinearOperator)
        assert A.domain.dimension == A.codomain.dimension
        domain = A.codomain
        codomain = A.domain

        if kwargs['x0'] is None:
            kwargs['x0'] = codomain.zeros()

        self._A = A
        self._domain = domain
        self._codomain = codomain

        self._check_options(**kwargs)
        self._options = kwargs

    @property
    def domain(self):
        return self._domain

    @property
    def codomain(self):
        return self._codomain

    @property
    def dtype(self):
        return None

    @property
    def linop(self):
        """
        The linear operator $A$ of which this object is the inverse $A^{-1}$.

        The linear operator $A$ can be modified in place, or replaced entirely
        through the setter. A substitution should only be made in cases where
        no other options are viable, as it breaks the one-to-one map between
        the original linear operator $A$ (passed to the constructor) and the
        current `InverseLinearOperator` object $A^{-1}$. Use with extreme care!

        """
        return self._A
    
    @linop.setter
    def linop(self, a):
        """ Set the linear operator $A$ of which this object is the inverse $A^{-1}$. """
        assert isinstance(a, LinearOperator)
        assert a.domain is self.domain
        assert a.codomain is self.codomain
        self._A = a

    def _check_options(self, **kwargs):
        """ Check whether the options passed to the solver class are valid. """
        for key, value in kwargs.items():

            if key == 'x0':
                if value is not None:
                    assert isinstance(value, Vector), "x0 must be a Vector or None"
                    assert value.space == self.codomain, "x0 belongs to the wrong VectorSpace"
            elif key == 'tol':
                assert is_real(value), "tol must be a real number"
                assert value > 0, "tol must be positive"
            elif key == 'maxiter':
                assert isinstance(value, int), "maxiter must be an int"
                assert value > 0, "maxiter must be positive"
            elif key == 'verbose':
                assert isinstance(value, bool), "verbose must be a bool"

    def get_info(self):
        """ Returns the previous convergence information. """
        return self._info

    def get_options(self, key=None):
        """Get a copy of all the solver options, or a specific value of interest.

        Parameters
        ----------
        key : str | None
            Name of the specific option of interest (default: None).

        Returns
        -------
        dict | type(self._options['key']) | None
            If `key` is given, get the specific option of interest. If there is
            no such option, `None` is returned instead. If `key` is not given,
            get a copy of all the solver options in a dictionary.

        """
        if key is None:
            return self._options.copy()
        else:
            return self._options.get(key)

    def set_options(self, **kwargs):
        """ Set the solver options by passing keyword arguments. """
        self._check_options(**kwargs)
        self._options.update(kwargs)

    def transpose(self, conjugate=False):
        cls     = type(self)
        At      = self.linop.transpose(conjugate=conjugate)
        options = self._options
        return cls(At, **options)

#===============================================================================
class LinearSolver(ABC):
    """
    Solver for the square linear system Ax=b, where x and b belong to the same vector space V.

    """
    @property
    def shape(self):
        return (self.space.dimension, self.space.dimension)

    #-------------------------------------
    # Deferred methods
    #-------------------------------------
    @property
    @abstractmethod
    def space(self):
        pass

    @abstractmethod
    def transpose(self):
        """Return the transpose of the LinearSolver."""
        pass

    @abstractmethod
    def solve(self, rhs, out=None):
        pass

    @property
    def T(self):
        return self.transpose()

#===============================================================================
class MatrixFreeLinearOperator(LinearOperator):
    """
    General linear operator represented by a callable dot method.

    Parameters
    ----------
    domain : VectorSpace
        The domain of the linear operator.
    
    codomain : VectorSpace
        The codomain of the linear operator.
    
    dot : Callable
        The method of the linear operator, assumed to map from domain to codomain.    
        This method can take out as an optional argument but this is not mandatory.

    dot_transpose: Callable
        The method of the transpose of the linear operator, assumed to map from codomain to domain.
        This method can take out as an optional argument but this is not mandatory.

    Examples
    --------
        # example 1: a matrix encapsulated as a (fake) matrix-free linear operator        
        A_SM = StencilMatrix(V, W)
        AT_SM = A_SM.transpose()
        A = MatrixFreeLinearOperator(domain=V, codomain=W, dot=lambda v: A_SM @ v, dot_transpose=lambda v: AT_SM @ v)

        # example 2: a truly matrix-free linear operator
        A = MatrixFreeLinearOperator(domain=V, codomain=V, dot=lambda v: 2*v, dot_transpose=lambda v: 2*v)

    """

    def __init__(self, domain, codomain, dot, dot_transpose=None):

        assert isinstance(domain, VectorSpace)
        assert isinstance(codomain, VectorSpace)       
        assert isinstance(dot, LambdaType)

        self._domain = domain
        self._codomain = codomain
        self._dot = dot

        sig =  signature(dot)
        self._dot_takes_out_arg = ('out' in [p.name for p in sig.parameters.values() if p.kind == p.KEYWORD_ONLY])

        if dot_transpose is not None:
            assert isinstance(dot_transpose, LambdaType)
            self._dot_transpose = dot_transpose
            sig =  signature(dot_transpose)
            self._dot_transpose_takes_out_arg = ('out' in [p.name for p in sig.parameters.values() if p.kind == p.KEYWORD_ONLY])
        else:
            self._dot_transpose = None
            self._dot_transpose_takes_out_arg = False            

    @property
    def domain(self):
        return self._domain

    @property
    def codomain(self):
        return self._codomain

    @property
    def dtype(self):
        return None

    def dot(self, v, out=None):
        assert isinstance(v, Vector)
        assert v.space == self.domain

        if out is not None:
            assert isinstance(out, Vector)
            assert out.space == self.codomain
        else:
            out = self.codomain.zeros()

        if self._dot_takes_out_arg:
            self._dot(v, out=out)
        else:
            # provided dot product does not take an out argument: we simply copy the result into out
            self._dot(v).copy(out=out)
                    
        return out
        
    def toarray(self):
        raise NotImplementedError('toarray() is not defined for MatrixFreeLinearOperator.')

    def tosparse(self):
        raise NotImplementedError('tosparse() is not defined for MatrixFreeLinearOperator.')
    
    def transpose(self, conjugate=False):
        if self._dot_transpose is None:
            raise NotImplementedError('no transpose dot method was given -- cannot create the transpose operator')
        
        if conjugate:
            if self._dot_transpose_takes_out_arg:
                new_dot = lambda v, out=None: self._dot_transpose(v, out=out).conjugate()
            else:
                new_dot = lambda v: self._dot_transpose(v).conjugate()
        else:
            new_dot = self._dot_transpose

        return MatrixFreeLinearOperator(domain=self.codomain, codomain=self.domain, dot=new_dot, dot_transpose=self._dot)
