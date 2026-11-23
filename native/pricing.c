#include <math.h>

/* C pricing/time estimate called from Python through ctypes.
   Returns 0 on success and -1 for invalid input. */
int scenesnap_quote(double decor_price,
                    double sourcing_cost,
                    double service_hours,
                    double hourly_rate,
                    double travel_fee,
                    int guest_count,
                    double *total,
                    int *planned_minutes) {
    if (!total || !planned_minutes ||
        !isfinite(decor_price) || !isfinite(sourcing_cost) ||
        !isfinite(service_hours) || !isfinite(hourly_rate) ||
        !isfinite(travel_fee) || decor_price < 0 || sourcing_cost < 0 ||
        service_hours < 0 || hourly_rate < 0 || travel_fee < 0 ||
        guest_count < 0 || guest_count > 10000) {
        return -1;
    }

    /* Allow 15 minutes of on-site handling per 20 guests, plus booked labor. */
    const double guest_hours = ((double)guest_count / 20.0) * 0.25;
    const double labor_hours = service_hours + guest_hours;
    const double amount = decor_price + sourcing_cost + travel_fee + (labor_hours * hourly_rate);
    if (!isfinite(amount) || amount > 10000000.0 || labor_hours > 100000.0) {
        return -1;
    }

    *total = amount;
    *planned_minutes = (int)ceil(labor_hours * 60.0);
    return 0;
}
