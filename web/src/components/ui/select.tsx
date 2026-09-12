import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

const selectVariants = cva(
  'rounded-md border border-borde bg-panel px-3 text-sm text-texto shadow-sm outline-none transition-colors ' +
    'hover:border-texto-suave focus-visible:border-acento focus-visible:ring-1 focus-visible:ring-acento ' +
    'disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      size: {
        default: 'h-9',
        sm: 'h-8 text-xs',
      },
    },
    defaultVariants: {
      size: 'default',
    },
  },
)

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'size'>,
    VariantProps<typeof selectVariants> {}

/**
 * Primitiva mínima estilo shadcn/ui sobre un `<select>` nativo (menos
 * fricción que el select compuesto de Radix para esta fase).
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, size, ...props }, ref) => (
    <select ref={ref} className={cn(selectVariants({ size }), className)} {...props} />
  ),
)
Select.displayName = 'Select'
